package cmd

import (
	"strings"
	"testing"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

func TestNoScoreNote(t *testing.T) {
	sha := "2222222222222222222222222222222222222222"
	commit := api.ScoredCommitRef{Sha: sha}
	cases := []struct {
		name  string
		score *api.CommitScore
		want  []string
	}{
		{"nothing checked", nil, nil},
		{"scored", &api.CommitScore{Outcome: api.OutcomeEnumScored, Commit: commit}, nil},
		{"failed", &api.CommitScore{Outcome: api.OutcomeEnumFailed, Commit: commit}, nil},
		{"checking", &api.CommitScore{Outcome: api.OutcomeEnumChecking, Commit: commit, Standards: api.StandardsProgress{Expected: 6, Finished: 3}},
			[]string{"Checking commit 2222222: 3 of 6 standards done…"}},
		{"no score", &api.CommitScore{Outcome: api.OutcomeEnumNoScore, Commit: commit, Reason: "Lint errored"},
			[]string{"No score on commit 2222222: Lint errored.", "gitgrit check --sha " + sha}},
		{"no reason on record", &api.CommitScore{Outcome: api.OutcomeEnumNoScore, Commit: commit},
			[]string{"(not every standard has a result)"[1:32]}},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			got := noScoreNote(c.score)
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
