package session

import (
	"net/http"
	"net/url"
	"strings"
	"testing"

	"github.com/kfirzvi-com/gitgrit/cli/internal/config"
)

func resp(status int, contentType string) *http.Response {
	u, _ := url.Parse("https://example.com/api/v1/me/")
	return &http.Response{StatusCode: status, Header: http.Header{"Content-Type": {contentType}}, Request: &http.Request{URL: u}}
}

func TestCheck(t *testing.T) {
	if err := Check(resp(200, "application/json"), []byte(`{}`)); err != nil {
		t.Errorf("JSON 200: %v", err)
	}
	if err := Check(resp(204, ""), nil); err != nil {
		t.Errorf("empty 204: %v", err)
	}
	if err := Check(resp(200, "text/html"), []byte("<html>")); err == nil || !strings.Contains(err.Error(), "GitGrit server") {
		t.Errorf("HTML 200: %v; want a not-GitGrit error", err)
	}
	err := Check(resp(404, "application/json"), []byte(`{"detail":"Workspace not found."}`))
	if err == nil || err.Error() != "HTTP 404: Workspace not found." {
		t.Errorf("404: %v", err)
	}
	if err := Check(resp(401, "application/json"), []byte(`{"detail":"Invalid token."}`)); err == nil || !strings.Contains(err.Error(), "gitgrit auth login") {
		t.Errorf("401 should hint at logging in: %v", err)
	}
}

func TestResolveHostOrder(t *testing.T) {
	cfg := &config.Config{DefaultHost: "app-staging.gitgrit.dev"}
	t.Setenv("GITGRIT_HOST", "")
	if h, _ := ResolveHost("", &config.Config{}); h != config.DefaultHost {
		t.Errorf("no settings: %s", h)
	}
	if h, _ := ResolveHost("", cfg); h != "https://app-staging.gitgrit.dev" {
		t.Errorf("saved default: %s", h)
	}
	t.Setenv("GITGRIT_HOST", "localhost:8001")
	if h, _ := ResolveHost("", cfg); h != "http://localhost:8001" {
		t.Errorf("env beats saved default: %s", h)
	}
	if h, _ := ResolveHost("app.gitgrit.dev", cfg); h != "https://app.gitgrit.dev" {
		t.Errorf("flag beats env: %s", h)
	}
}
