// Package auth signs the CLI in to a GitGrit instance with OAuth 2.0: the
// authorization code flow with PKCE (S256) and a loopback redirect (RFC 8252),
// the way gh and gcloud do. The server is django-oauth-toolkit; its endpoints
// are discovered from /.well-known/oauth-authorization-server (RFC 8414).
package auth

import (
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"html"
	"io"
	"net"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// ClientID is the public client every GitGrit instance registers for the CLI.
const ClientID = "gitgrit-cli"

// Scopes the CLI asks for.
const Scopes = "read write"

// Metadata is the part of the RFC 8414 document the CLI uses.
type Metadata struct {
	Issuer                string `json:"issuer"`
	AuthorizationEndpoint string `json:"authorization_endpoint"`
	TokenEndpoint         string `json:"token_endpoint"`
	RevocationEndpoint    string `json:"revocation_endpoint"`
}

// Discover fetches the server's OAuth metadata.
func Discover(ctx context.Context, hc *http.Client, host string) (*Metadata, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, host+"/.well-known/oauth-authorization-server", nil)
	if err != nil {
		return nil, err
	}
	resp, err := hc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("reaching %s: %w", host, err)
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("%s does not look like a GitGrit server (OAuth discovery: HTTP %d)", host, resp.StatusCode)
	}
	var md Metadata
	if err := json.NewDecoder(resp.Body).Decode(&md); err != nil {
		return nil, fmt.Errorf("reading OAuth metadata: %w", err)
	}
	if md.AuthorizationEndpoint == "" || md.TokenEndpoint == "" {
		return nil, errors.New("server's OAuth metadata has no authorization or token endpoint")
	}
	return &md, nil
}

// Token is a token endpoint response.
type Token struct {
	AccessToken  string `json:"access_token"`
	RefreshToken string `json:"refresh_token"`
	ExpiresIn    int    `json:"expires_in"`
	Scope        string `json:"scope"`
	TokenType    string `json:"token_type"`

	obtained time.Time
}

// Expiry is when the access token stops working.
func (t *Token) Expiry() time.Time {
	return t.obtained.Add(time.Duration(t.ExpiresIn) * time.Second)
}

func randomString(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return base64.RawURLEncoding.EncodeToString(b)
}

// NewPKCE returns a code verifier and its S256 challenge (RFC 7636).
func NewPKCE() (verifier, challenge string) {
	verifier = randomString(48)
	sum := sha256.Sum256([]byte(verifier))
	return verifier, base64.RawURLEncoding.EncodeToString(sum[:])
}

// LoginOptions tune Login.
type LoginOptions struct {
	// OpenBrowser opens the authorization URL; nil or a failure falls back
	// to asking the user to open it.
	OpenBrowser func(string) error
	// Out receives the "open this URL" message.
	Out io.Writer
	// Timeout bounds the wait for the browser (default 5 minutes).
	Timeout time.Duration
}

type callback struct {
	code string
	err  error
}

// Login runs the browser flow and returns the issued token.
func Login(ctx context.Context, hc *http.Client, md *Metadata, opts LoginOptions) (*Token, error) {
	if opts.Timeout == 0 {
		opts.Timeout = 5 * time.Minute
	}
	ctx, cancel := context.WithTimeout(ctx, opts.Timeout)
	defer cancel()

	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		return nil, fmt.Errorf("starting the local callback listener: %w", err)
	}
	defer ln.Close()
	redirectURI := fmt.Sprintf("http://127.0.0.1:%d/callback", ln.Addr().(*net.TCPAddr).Port)

	verifier, challenge := NewPKCE()
	state := randomString(24)
	authURL := md.AuthorizationEndpoint + "?" + url.Values{
		"response_type":         {"code"},
		"client_id":             {ClientID},
		"redirect_uri":          {redirectURI},
		"scope":                 {Scopes},
		"state":                 {state},
		"code_challenge":        {challenge},
		"code_challenge_method": {"S256"},
	}.Encode()

	results := make(chan callback, 1)
	srv := &http.Server{
		ReadHeaderTimeout: 10 * time.Second,
		Handler: http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if r.URL.Path != "/callback" {
				http.NotFound(w, r)
				return
			}
			res := readCallback(r.URL.Query(), state, md.Issuer)
			w.Header().Set("Content-Type", "text/html; charset=utf-8")
			if res.err != nil {
				w.WriteHeader(http.StatusBadRequest)
				fmt.Fprintf(w, page, "Sign-in failed", html.EscapeString(res.err.Error()))
			} else {
				fmt.Fprintf(w, page, "Signed in", "You can close this tab and return to the terminal.")
			}
			select {
			case results <- res:
			default:
			}
		}),
	}
	go srv.Serve(ln) //nolint:errcheck // Serve returns when the listener closes.
	defer srv.Close()

	if opts.Out != nil {
		fmt.Fprintf(opts.Out, "Opening your browser to sign in. If it doesn't open, visit:\n\n  %s\n\n", authURL)
	}
	if opts.OpenBrowser != nil {
		_ = opts.OpenBrowser(authURL)
	}

	var res callback
	select {
	case res = <-results:
	case <-ctx.Done():
		return nil, errors.New("timed out waiting for the browser sign-in")
	}
	if res.err != nil {
		return nil, res.err
	}
	return postToken(ctx, hc, md.TokenEndpoint, url.Values{
		"grant_type":    {"authorization_code"},
		"code":          {res.code},
		"redirect_uri":  {redirectURI},
		"client_id":     {ClientID},
		"code_verifier": {verifier},
	})
}

func readCallback(q url.Values, state, issuer string) callback {
	if e := q.Get("error"); e != "" {
		if d := q.Get("error_description"); d != "" {
			e += ": " + d
		}
		return callback{err: fmt.Errorf("authorization denied (%s)", e)}
	}
	if q.Get("state") != state {
		return callback{err: errors.New("state mismatch: ignoring a callback this login did not start")}
	}
	// RFC 9207: the response names its issuer, defeating mix-up attacks.
	if iss := q.Get("iss"); iss != "" && issuer != "" && strings.TrimRight(iss, "/") != strings.TrimRight(issuer, "/") {
		return callback{err: fmt.Errorf("issuer mismatch: expected %s, got %s", issuer, iss)}
	}
	code := q.Get("code")
	if code == "" {
		return callback{err: errors.New("no authorization code in the callback")}
	}
	return callback{code: code}
}

// Refresh trades a refresh token for a new token (the refresh token rotates).
func Refresh(ctx context.Context, hc *http.Client, md *Metadata, refreshToken string) (*Token, error) {
	return postToken(ctx, hc, md.TokenEndpoint, url.Values{
		"grant_type":    {"refresh_token"},
		"refresh_token": {refreshToken},
		"client_id":     {ClientID},
	})
}

// Revoke revokes a token (RFC 7009). Unknown tokens are not an error.
func Revoke(ctx context.Context, hc *http.Client, md *Metadata, token string) error {
	if md.RevocationEndpoint == "" || token == "" {
		return nil
	}
	resp, err := postForm(ctx, hc, md.RevocationEndpoint, url.Values{"token": {token}, "client_id": {ClientID}})
	if err != nil {
		return err
	}
	resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("revoking the token: HTTP %d", resp.StatusCode)
	}
	return nil
}

func postForm(ctx context.Context, hc *http.Client, endpoint string, form url.Values) (*http.Response, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, strings.NewReader(form.Encode()))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	req.Header.Set("Accept", "application/json")
	return hc.Do(req)
}

func postToken(ctx context.Context, hc *http.Client, endpoint string, form url.Values) (*Token, error) {
	resp, err := postForm(ctx, hc, endpoint, form)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if resp.StatusCode != http.StatusOK {
		var e struct {
			Error       string `json:"error"`
			Description string `json:"error_description"`
		}
		_ = json.Unmarshal(body, &e)
		if e.Error == "" {
			e.Error = resp.Status
		}
		return nil, &TokenError{Code: e.Error, Description: e.Description}
	}
	tok := &Token{obtained: time.Now()}
	if err := json.Unmarshal(body, tok); err != nil {
		return nil, fmt.Errorf("reading the token response: %w", err)
	}
	if tok.AccessToken == "" {
		return nil, errors.New("token response has no access_token")
	}
	return tok, nil
}

// TokenError is an OAuth error from the token endpoint, e.g. invalid_grant
// when a refresh token has expired or been revoked.
type TokenError struct {
	Code        string
	Description string
}

func (e *TokenError) Error() string {
	if e.Description != "" {
		return e.Code + ": " + e.Description
	}
	return e.Code
}

const page = `<!doctype html><meta charset="utf-8"><title>GitGrit CLI</title>
<body style="font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;display:grid;place-items:center;height:100vh;margin:0">
<div style="text-align:center"><h1 style="font-size:1.5rem">%s</h1><p>%s</p></div></body>`
