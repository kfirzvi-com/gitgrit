package config

import (
	"os"
	"path/filepath"
	"testing"
	"time"
)

func TestNormalizeHost(t *testing.T) {
	ok := map[string]string{
		"app.gitgrit.dev":             "https://app.gitgrit.dev",
		"https://app.gitgrit.dev/":    "https://app.gitgrit.dev",
		"https://App.GitGrit.dev/x/y": "https://app.gitgrit.dev",
		"localhost:8001":              "http://localhost:8001",
		"127.0.0.1:8000":              "http://127.0.0.1:8000",
		"[::1]:8000":                  "http://[::1]:8000",
		"http://localhost:8001":       "http://localhost:8001",
		"https://localhost:8443":      "https://localhost:8443",
		"app-staging.gitgrit.dev":     "https://app-staging.gitgrit.dev",
		"gitgrit.acme.internal:8443":  "https://gitgrit.acme.internal:8443",
	}
	for in, want := range ok {
		got, err := NormalizeHost(in)
		if err != nil || got != want {
			t.Errorf("NormalizeHost(%q) = %q, %v; want %q", in, got, err, want)
		}
	}
	for _, in := range []string{"", "http://app.gitgrit.dev", "ftp://x", "http://127.0.0.1.evil.com"} {
		if got, err := NormalizeHost(in); err == nil {
			t.Errorf("NormalizeHost(%q) = %q; want error", in, got)
		}
	}
}

func TestSaveLoadRoundTripIsPrivate(t *testing.T) {
	dir := t.TempDir()
	t.Setenv("GITGRIT_CONFIG_DIR", dir)
	c, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	c.DefaultHost = "http://localhost:8001"
	h := c.Host("http://localhost:8001")
	h.AccessToken = "secret"
	h.Expiry = time.Date(2030, 1, 1, 0, 0, 0, 0, time.UTC)
	if err := c.Save(); err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(filepath.Join(dir, "hosts.yml"))
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("hosts.yml mode = %v; want 0600", info.Mode().Perm())
	}
	again, err := Load()
	if err != nil {
		t.Fatal(err)
	}
	got := again.Hosts["http://localhost:8001"]
	if got == nil || got.AccessToken != "secret" || !got.Expiry.Equal(h.Expiry) || again.DefaultHost != c.DefaultHost {
		t.Errorf("round trip lost data: %+v", again)
	}
}
