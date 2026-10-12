// Package session is what every command talks to the server through: it
// picks the GitGrit instance, supplies (and refreshes) credentials, and
// resolves "which workspace" and "which project".
package session

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/auth"
	"github.com/kfirzvi-com/gitgrit/cli/internal/config"
	"github.com/kfirzvi-com/gitgrit/cli/internal/gitctx"
	"github.com/kfirzvi-com/gitgrit/cli/internal/version"
)

// Session is one CLI invocation's connection to one GitGrit instance.
type Session struct {
	Host   string
	Config *config.Config
	HTTP   *http.Client
	API    *api.ClientWithResponses

	// ServerVersion is the X-GitGrit-Version of the last response.
	ServerVersion string

	envToken string
	md       *auth.Metadata
}

// ResolveHost picks the instance: the --host flag, then $GITGRIT_HOST, then
// the default saved by `gitgrit auth login`, then app.gitgrit.dev.
func ResolveHost(flag string, cfg *config.Config) (string, error) {
	for _, h := range []string{flag, os.Getenv("GITGRIT_HOST"), cfg.DefaultHost} {
		if h != "" {
			return config.NormalizeHost(h)
		}
	}
	return config.DefaultHost, nil
}

// Open prepares a session for the resolved host.
func Open(hostFlag string) (*Session, error) {
	cfg, err := config.Load()
	if err != nil {
		return nil, err
	}
	host, err := ResolveHost(hostFlag, cfg)
	if err != nil {
		return nil, err
	}
	s := &Session{Host: host, Config: cfg, envToken: os.Getenv("GITGRIT_TOKEN")}
	s.HTTP = &http.Client{Timeout: 60 * time.Second, Transport: &versionTransport{s: s, next: http.DefaultTransport}}
	s.API, err = api.NewClientWithResponses(host, api.WithHTTPClient(s.HTTP), api.WithRequestEditorFn(s.authorize))
	return s, err
}

type versionTransport struct {
	s    *Session
	next http.RoundTripper
}

func (t *versionTransport) RoundTrip(req *http.Request) (*http.Response, error) {
	req.Header.Set("User-Agent", version.UserAgent())
	resp, err := t.next.RoundTrip(req)
	if err == nil {
		if v := resp.Header.Get("X-GitGrit-Version"); v != "" {
			t.s.ServerVersion = v
		}
	}
	return resp, err
}

// NotLoggedInError means there are no credentials for the host.
type NotLoggedInError struct{ Host string }

func (e *NotLoggedInError) Error() string {
	login := "gitgrit auth login"
	if e.Host != config.DefaultHost {
		login += " --host " + strings.TrimPrefix(strings.TrimPrefix(e.Host, "https://"), "http://")
	}
	return fmt.Sprintf("not logged in to %s; run `%s` or set GITGRIT_TOKEN", e.Host, login)
}

// UsingEnvToken reports whether $GITGRIT_TOKEN supplies the credentials.
func (s *Session) UsingEnvToken() bool { return s.envToken != "" }

// HostConfig is the saved entry for this host, or nil.
func (s *Session) HostConfig() *config.Host { return s.Config.Hosts[s.Host] }

// Metadata discovers (once) the host's OAuth endpoints.
func (s *Session) Metadata(ctx context.Context) (*auth.Metadata, error) {
	if s.md == nil {
		md, err := auth.Discover(ctx, s.HTTP, s.Host)
		if err != nil {
			return nil, err
		}
		s.md = md
	}
	return s.md, nil
}

// Token returns a usable access token, refreshing an expiring OAuth token.
func (s *Session) Token(ctx context.Context) (string, error) {
	if s.envToken != "" {
		return s.envToken, nil
	}
	h := s.HostConfig()
	if h == nil || h.AccessToken == "" {
		return "", &NotLoggedInError{Host: s.Host}
	}
	if h.RefreshToken != "" && !h.Expiry.IsZero() && time.Until(h.Expiry) < time.Minute {
		md, err := s.Metadata(ctx)
		if err != nil {
			return "", err
		}
		tok, err := auth.Refresh(ctx, s.HTTP, md, h.RefreshToken)
		if err != nil {
			var te *auth.TokenError
			if errors.As(err, &te) {
				return "", fmt.Errorf("your session on %s has expired (%s); run `gitgrit auth login` again", s.Host, te.Code)
			}
			return "", err
		}
		h.AccessToken, h.RefreshToken, h.Expiry = tok.AccessToken, tok.RefreshToken, tok.Expiry()
		if err := s.Config.Save(); err != nil {
			return "", err
		}
	}
	return h.AccessToken, nil
}

func (s *Session) authorize(ctx context.Context, req *http.Request) error {
	tok, err := s.Token(ctx)
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+tok)
	return nil
}

// APIError is a non-2xx API response.
type APIError struct {
	Status int
	Detail string
}

func (e *APIError) Error() string { return fmt.Sprintf("HTTP %d: %s", e.Status, e.Detail) }

// Check turns a generated client response into an error unless it's a 2xx
// JSON response (or an empty one). Anything else — say an HTML page from a
// proxy, or a --host that isn't GitGrit — would decode to nothing.
func Check(resp *http.Response, body []byte) error {
	if resp.StatusCode >= 200 && resp.StatusCode < 300 {
		if len(body) == 0 || strings.Contains(resp.Header.Get("Content-Type"), "json") {
			return nil
		}
		return fmt.Errorf("unexpected %q response from %s; is it a GitGrit server?",
			resp.Header.Get("Content-Type"), resp.Request.URL.Host)
	}
	detail := strings.TrimSpace(string(body))
	var d struct {
		Detail string `json:"detail"`
	}
	if json.Unmarshal(body, &d) == nil && d.Detail != "" {
		detail = d.Detail
	}
	if resp.StatusCode == http.StatusUnauthorized {
		detail += " (log in again with `gitgrit auth login`, or check GITGRIT_TOKEN)"
	}
	if len(detail) > 500 {
		detail = detail[:500] + "…"
	}
	return &APIError{Status: resp.StatusCode, Detail: detail}
}

// Me is GET /api/v1/me/.
func (s *Session) Me(ctx context.Context) (*api.Me, error) {
	resp, err := s.API.GetMeWithResponse(ctx)
	if err != nil {
		return nil, err
	}
	if err := Check(resp.HTTPResponse, resp.Body); err != nil {
		return nil, err
	}
	return resp.JSON200, nil
}

// Workspace identifies the workspace a command acts on.
type Workspace struct {
	ID   uuid.UUID
	Name string
}

// Workspace picks the workspace: the --workspace flag (id or name), then
// $GITGRIT_WORKSPACE, then the one saved by `gitgrit workspace use`; failing
// those, the only workspace the token can reach.
func (s *Session) Workspace(ctx context.Context, flag string) (Workspace, error) {
	want, saved := flag, ""
	if want == "" {
		want = os.Getenv("GITGRIT_WORKSPACE")
	}
	if want == "" && !s.UsingEnvToken() {
		if h := s.HostConfig(); h != nil {
			want, saved = h.Workspace, h.WorkspaceName
		}
	}
	if id, err := uuid.Parse(want); err == nil {
		return Workspace{ID: id, Name: saved}, nil
	}
	me, err := s.Me(ctx)
	if err != nil {
		return Workspace{}, err
	}
	names := make([]string, 0, len(me.Workspaces))
	for _, w := range me.Workspaces {
		if want != "" && strings.EqualFold(w.Name, want) {
			return Workspace{ID: w.Id, Name: w.Name}, nil
		}
		names = append(names, w.Name)
	}
	if want != "" {
		return Workspace{}, fmt.Errorf("no workspace %q; you can use: %s", want, strings.Join(names, ", "))
	}
	switch len(me.Workspaces) {
	case 0:
		return Workspace{}, errors.New("this account is not in any workspace yet")
	case 1:
		return Workspace{ID: me.Workspaces[0].Id, Name: me.Workspaces[0].Name}, nil
	}
	return Workspace{}, fmt.Errorf("pick a workspace with `gitgrit workspace use <name>` or --workspace; you can use: %s", strings.Join(names, ", "))
}

// Project identifies the project a command acts on.
type Project struct {
	ID       uuid.UUID
	Name     string
	FullPath string
	Default  string // default branch
}

// Project picks the project: --project (id or org/repo), else the git repo
// in the current directory (its origin remote).
func (s *Session) Project(ctx context.Context, ws Workspace, flag string) (Project, error) {
	if id, err := uuid.Parse(flag); err == nil {
		return Project{ID: id, Name: flag}, nil
	}
	params := &api.ResolveProjectParams{}
	if flag != "" {
		params.RepoFullPath = &flag
	} else {
		remote := gitctx.OriginURL()
		if remote == "" {
			return Project{}, errors.New("not in a git repository with an `origin` remote; pass --project <org/repo>")
		}
		safe, path := gitctx.SafeRemote(remote), gitctx.FullPath(remote)
		params.WebUrl = &safe
		if path != "" {
			params.RepoFullPath = &path
		}
	}
	resp, err := s.API.ResolveProjectWithResponse(ctx, ws.ID, params)
	if err != nil {
		return Project{}, err
	}
	if resp.JSON404 != nil {
		msg := "this repository is not a project in " + nameOr(ws)
		if flag != "" {
			msg = fmt.Sprintf("no project %q in %s", flag, nameOr(ws))
		}
		if len(resp.JSON404.Candidates) > 0 {
			msg += "; did you mean: " + strings.Join(resp.JSON404.Candidates, ", ")
		}
		return Project{}, errors.New(msg)
	}
	if err := Check(resp.HTTPResponse, resp.Body); err != nil {
		return Project{}, err
	}
	p := resp.JSON200
	return Project{ID: p.Id, Name: p.Name, FullPath: p.FullPath, Default: p.DefaultBranch}, nil
}

func nameOr(ws Workspace) string {
	if ws.Name != "" {
		return "workspace " + ws.Name
	}
	return "this workspace"
}
