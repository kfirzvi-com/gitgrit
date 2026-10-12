package cmd

import (
	"context"
	"net/http"
	"strings"

	"github.com/kfirzvi-com/gitgrit/cli/internal/session"
)

func checkResp(resp *http.Response, body []byte) error { return session.Check(resp, body) }

func equalFold(a, b string) bool { return strings.EqualFold(a, b) }

// target resolves the session, workspace and (when project is true) the
// project a command acts on.
type target struct {
	s  *session.Session
	ws session.Workspace
	p  session.Project
}

func resolve(ctx context.Context, projectFlag string, project bool) (*target, error) {
	s, err := open()
	if err != nil {
		return nil, err
	}
	ws, err := s.Workspace(ctx, workspaceFlag)
	if err != nil {
		return nil, err
	}
	t := &target{s: s, ws: ws}
	if project {
		if t.p, err = s.Project(ctx, ws, projectFlag); err != nil {
			return nil, err
		}
	}
	return t, nil
}
