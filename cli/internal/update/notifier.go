package update

import (
	"context"
	"errors"
	"net/http"
	"os"
	"path/filepath"
	"time"

	"gopkg.in/yaml.v3"
)

const checkEvery = 24 * time.Hour

type state struct {
	CheckedAt time.Time `yaml:"checked_at"`
	Channel   string    `yaml:"channel"`
	Latest    string    `yaml:"latest"`
}

// NotifierDisabled reports whether update notices are off: in CI, when
// GITGRIT_NO_UPDATE_NOTIFIER is set, or for local builds.
func NotifierDisabled(isDev bool) bool {
	return isDev || os.Getenv("GITGRIT_NO_UPDATE_NOTIFIER") != "" || os.Getenv("CI") != ""
}

// Notice returns the newer version on channel, if any, at most once a day
// over the network; between checks it answers from state.yml in dir.
func Notice(ctx context.Context, dir, current, channel string) string {
	path := filepath.Join(dir, "state.yml")
	var st state
	if data, err := os.ReadFile(path); err == nil {
		_ = yaml.Unmarshal(data, &st)
	}
	if st.Channel != channel || time.Since(st.CheckedAt) > checkEvery {
		ctx, cancel := context.WithTimeout(ctx, 3*time.Second)
		defer cancel()
		r, err := Latest(ctx, &http.Client{}, channel)
		if err != nil && !errors.Is(err, context.Canceled) {
			return ""
		}
		if r != nil {
			st = state{CheckedAt: time.Now(), Channel: channel, Latest: r.Version()}
			if data, err := yaml.Marshal(st); err == nil {
				_ = os.MkdirAll(dir, 0o700)
				_ = os.WriteFile(path, data, 0o600)
			}
		}
	}
	if Newer(current, st.Latest, channel) {
		return st.Latest
	}
	return ""
}
