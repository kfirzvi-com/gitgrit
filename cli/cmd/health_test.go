package cmd

import (
	"strings"
	"testing"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

func TestOlderCommitNote(t *testing.T) {
	older := "1111111111111111111111111111111111111111"
	newest := "2222222222222222222222222222222222222222"
	shown := &api.CommitScore{Commit: api.ScoredCommitRef{Sha: older}}
	cases := []struct {
		name  string
		score *api.CommitScore
		newer *api.NewerCommit
		want  []string
	}{
		{"no newer commit", shown, nil, nil},
		{"a newer commit still checking", shown, &api.NewerCommit{Sha: newest, Outcome: api.Checking}, nil},
		{"a newer commit with no score", shown, &api.NewerCommit{Sha: newest, Outcome: api.NoScore, Reason: "Lint errored"},
			[]string{"Not the latest commit: showing 1111111.", "The newest, 2222222, has no score (Lint errored).", "gitgrit check --sha " + newest}},
		{"no score at all", nil, &api.NewerCommit{Sha: newest, Outcome: api.NoScore, Reason: "Docs not run"},
			[]string{"No score: the newest commit, 2222222, has none (Docs not run)."}},
		{"no reason on record", shown, &api.NewerCommit{Sha: newest, Outcome: api.NoScore},
			[]string{"(not every standard has a result)"}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := olderCommitNote(c.score, c.newer)
			if c.want == nil {
				if got != "" {
					t.Errorf("got %q; want nothing", got)
				}
				return
			}
			for _, w := range c.want {
				if !strings.Contains(got, w) {
					t.Errorf("%q lacks %q", got, w)
				}
			}
		})
	}
}
