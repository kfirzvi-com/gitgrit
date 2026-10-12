// Package config stores the CLI's per-server state in hosts.yml: credentials
// and the default workspace for each GitGrit instance (production, staging,
// a local dev server), plus which one is the default.
package config

import (
	"errors"
	"fmt"
	"net"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// DefaultHost is the hosted GitGrit.
const DefaultHost = "https://app.gitgrit.dev"

// Host is what the CLI keeps for one GitGrit instance.
type Host struct {
	AccessToken   string    `yaml:"access_token,omitempty"`
	RefreshToken  string    `yaml:"refresh_token,omitempty"`
	Expiry        time.Time `yaml:"expiry,omitempty"`
	User          string    `yaml:"user,omitempty"`
	Workspace     string    `yaml:"workspace,omitempty"`
	WorkspaceName string    `yaml:"workspace_name,omitempty"`
}

// Config is the whole hosts.yml.
type Config struct {
	DefaultHost string           `yaml:"default_host,omitempty"`
	Hosts       map[string]*Host `yaml:"hosts,omitempty"`

	path string
}

// Dir is where the CLI keeps its files: $GITGRIT_CONFIG_DIR, else
// $XDG_CONFIG_HOME/gitgrit, else ~/.config/gitgrit.
func Dir() (string, error) {
	if d := os.Getenv("GITGRIT_CONFIG_DIR"); d != "" {
		return d, nil
	}
	if d := os.Getenv("XDG_CONFIG_HOME"); d != "" {
		return filepath.Join(d, "gitgrit"), nil
	}
	home, err := os.UserHomeDir()
	if err != nil {
		return "", err
	}
	return filepath.Join(home, ".config", "gitgrit"), nil
}

// Load reads hosts.yml; a missing file is an empty config.
func Load() (*Config, error) {
	dir, err := Dir()
	if err != nil {
		return nil, err
	}
	c := &Config{path: filepath.Join(dir, "hosts.yml"), Hosts: map[string]*Host{}}
	data, err := os.ReadFile(c.path)
	if errors.Is(err, os.ErrNotExist) {
		return c, nil
	}
	if err != nil {
		return nil, err
	}
	if err := yaml.Unmarshal(data, c); err != nil {
		return nil, fmt.Errorf("reading %s: %w", c.path, err)
	}
	if c.Hosts == nil {
		c.Hosts = map[string]*Host{}
	}
	return c, nil
}

// Save writes hosts.yml atomically, readable by the owner only: it holds
// tokens.
func (c *Config) Save() error {
	if err := os.MkdirAll(filepath.Dir(c.path), 0o700); err != nil {
		return err
	}
	data, err := yaml.Marshal(c)
	if err != nil {
		return err
	}
	tmp, err := os.CreateTemp(filepath.Dir(c.path), ".hosts-*.yml")
	if err != nil {
		return err
	}
	defer os.Remove(tmp.Name())
	if err := tmp.Chmod(0o600); err != nil {
		tmp.Close()
		return err
	}
	if _, err := tmp.Write(data); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	return os.Rename(tmp.Name(), c.path)
}

// Path is the file Load read from and Save writes to.
func (c *Config) Path() string { return c.path }

// Host returns the entry for a normalized host, creating it.
func (c *Config) Host(host string) *Host {
	h, ok := c.Hosts[host]
	if !ok {
		h = &Host{}
		c.Hosts[host] = h
	}
	return h
}

// IsLoopback reports whether a hostname is this machine.
func IsLoopback(hostname string) bool {
	if hostname == "localhost" || strings.HasSuffix(hostname, ".localhost") {
		return true
	}
	ip := net.ParseIP(hostname)
	return ip != nil && ip.IsLoopback()
}

// NormalizeHost turns what a user types ("localhost:8001",
// "app-staging.gitgrit.dev", "https://app.gitgrit.dev/") into a base URL.
// Without a scheme, local hosts get http and everything else https. Plain
// http to a non-local host is refused: tokens would cross the network in
// the clear.
func NormalizeHost(raw string) (string, error) {
	raw = strings.TrimSpace(raw)
	if raw == "" {
		return "", errors.New("empty host")
	}
	if !strings.Contains(raw, "://") {
		hostOnly := raw
		if h, _, err := net.SplitHostPort(raw); err == nil {
			hostOnly = h
		}
		scheme := "https"
		if IsLoopback(strings.Trim(hostOnly, "[]")) {
			scheme = "http"
		}
		raw = scheme + "://" + raw
	}
	u, err := url.Parse(raw)
	if err != nil || u.Host == "" {
		return "", fmt.Errorf("invalid host %q", raw)
	}
	switch u.Scheme {
	case "https":
	case "http":
		if !IsLoopback(u.Hostname()) {
			return "", fmt.Errorf("refusing plain http for %s: use https", u.Host)
		}
	default:
		return "", fmt.Errorf("unsupported scheme %q", u.Scheme)
	}
	return u.Scheme + "://" + strings.ToLower(u.Host), nil
}
