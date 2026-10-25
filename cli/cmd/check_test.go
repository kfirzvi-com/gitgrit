package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

const (
	wsID   = "0b0f1c2e-3d4a-4b5c-8d9e-0f1a2b3c4d5e"
	projID = "11111111-2222-3333-4444-555555555555"
	sha    = "cccccccccccccccccccccccccccccccccccccccc"
)

// fakeAPI serves the endpoints `check --wait` uses. The commit reports
// "running" for the first polls, then the given final result: ``failed``
// of two standards failed, scored as the server would (the variants below
// set another outcome: failed by a Required standard, or no_score).
func fakeAPI(t *testing.T, failed int, commitSHA *string) *httptest.Server {
	return fakeAPIWith(t, failed, commitSHA, "scored", "")
}

func fakeAPIWith(t *testing.T, failed int, commitSHA *string, outcome, reason string) *httptest.Server {
	var polls atomic.Int32
	mux := http.NewServeMux()
	prefix := "/api/v1/workspaces/" + wsID + "/projects/"
	mux.HandleFunc(prefix+"resolve/", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{
			"id": projID, "name": "api", "full_path": "acme/api", "default_branch": "main",
			"description": "", "platform": "github", "web_url": "", "lifecycle": "", "languages": []string{}, "tags": []string{}, "matched_by": "full_path",
		})
	})
	mux.HandleFunc(prefix+projID+"/checks/", func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer grit_ws_test" {
			t.Errorf("missing bearer token")
		}
		w.WriteHeader(http.StatusAccepted)
		json.NewEncoder(w).Encode(map[string]any{
			"branch": "main", "commit_sha": commitSHA, "queued": 2, "already_running": 0, "message": "Running 2 standards.",
		})
	})
	commit := func() map[string]any {
		running := 0
		if polls.Add(1) < 3 {
			running = 2
		}
		var score any = 100 - 50*failed
		now, grade, tone := outcome, "A+", "healthy"
		if failed > 0 {
			grade, tone = "C", "needs_attention"
		}
		switch {
		case running > 0:
			score, now, grade, tone = nil, "checking", "—", "unknown"
		case outcome == "failed":
			// Failed is a verdict, not a number.
			score, grade, tone = nil, "F", "failed"
		case outcome == "no_score":
			score, grade, tone = nil, "—", "unknown"
		}
		display := map[string]any{"text": grade, "tone": tone, "spoken": ""}
		return map[string]any{
			"sha": sha, "title": "Fix", "author": "Dana", "date": nil, "url": "", "checked": true, "running": running,
			"score": score, "score_display": display, "passed": 2 - failed, "failed": failed, "errored": 0,
			"commit_score": map[string]any{
				"outcome": now, "value": score, "reason": reason, "display": display,
				"standards": map[string]any{"expected": 2, "finished": 2},
				"commit":    map[string]any{"sha": sha, "branch": "main", "committed_at": nil},
			},
			"results": []any{}, "expected_but_never_ran": []any{},
		}
	}
	mux.HandleFunc(prefix+projID+"/commits/"+sha+"/", func(w http.ResponseWriter, r *http.Request) {
		if polls.Load() == 0 {
			polls.Add(1)
			http.Error(w, `{"detail":"No checks recorded"}`, http.StatusNotFound)
			return
		}
		json.NewEncoder(w).Encode(commit())
	})
	mux.HandleFunc(prefix+projID+"/commits/", func(w http.ResponseWriter, r *http.Request) {
		json.NewEncoder(w).Encode(map[string]any{"branch": "main", "page": 1, "has_more": false, "commits": []any{commit()}})
	})
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		mux.ServeHTTP(w, r)
	}))
	t.Cleanup(srv.Close)
	return srv
}

func runCLI(t *testing.T, srv *httptest.Server, args ...string) (string, error) {
	t.Setenv("GITGRIT_CONFIG_DIR", t.TempDir())
	t.Setenv("GITGRIT_HOST", srv.URL)
	t.Setenv("GITGRIT_TOKEN", "grit_ws_test")
	t.Setenv("GITGRIT_WORKSPACE", wsID)
	t.Setenv("GITGRIT_NO_UPDATE_NOTIFIER", "1")
	pollEvery = 10 * time.Millisecond
	hostFlag, workspaceFlag, jsonFlag = "", "", false
	root := newRoot()
	var out bytes.Buffer
	root.SetOut(&out)
	root.SetErr(&out)
	root.SetArgs(args)
	err := root.Execute()
	return out.String(), err
}

func exitCode(err error) int {
	var e *ExitError
	if errors.As(err, &e) {
		return e.Code
	}
	if err != nil {
		return 1
	}
	return 0
}

func TestCheckWaitPasses(t *testing.T) {
	s := sha
	out, err := runCLI(t, fakeAPI(t, 0, &s), "check", "--project", "acme/api", "--branch", "main", "--sha", sha, "--wait")
	if exitCode(err) != 0 {
		t.Fatalf("exit %d (%v); output:\n%s", exitCode(err), err, out)
	}
	if !strings.Contains(out, "2 passed, 0 failed") {
		t.Errorf("output lacks the result:\n%s", out)
	}
}

func TestCheckWaitPassesWhenOnlyAMajorStandardFails(t *testing.T) {
	s := sha
	out, err := runCLI(t, fakeAPI(t, 1, &s), "check", "--project", "acme/api", "--sha", sha, "--wait")
	if exitCode(err) != 0 {
		t.Fatalf("exit %d; want 0; output:\n%s", exitCode(err), out)
	}
}

func TestCheckWaitFailsWhenARequiredStandardFails(t *testing.T) {
	s := sha
	out, err := runCLI(t, fakeAPIWith(t, 1, &s, "failed", "No secrets failing"), "check", "-p", "acme/api", "--sha", sha, "--wait")
	if exitCode(err) != 1 || !strings.Contains(out, "Failed: No secrets failing.") {
		t.Fatalf("exit %d; want 1 with the reason; output:\n%s", exitCode(err), out)
	}
}

func TestCheckWaitExitsTwoWithoutAScoreAndSaysWhy(t *testing.T) {
	s := sha
	out, err := runCLI(t, fakeAPIWith(t, 0, &s, "no_score", "Lint errored, Docs not run"), "check", "-p", "acme/api", "--sha", sha, "--wait")
	if exitCode(err) != 2 || !strings.Contains(out, "No score: Lint errored, Docs not run.") {
		t.Fatalf("exit %d; want 2 with the reason; output:\n%s", exitCode(err), out)
	}
}

func TestVerdictByOutcome(t *testing.T) {
	value := func(v int) *int { return &v }
	cases := []struct {
		name      string
		score     *api.CommitScore
		failUnder int
		code      int
		why       string
	}{
		{"no outcome yet", nil, -1, 2, "No score: the commit has no outcome yet."},
		{"checking", &api.CommitScore{Outcome: api.OutcomeEnumChecking}, -1, 2, "No score: the commit is still being checked."},
		{"no score with a reason", &api.CommitScore{Outcome: api.OutcomeEnumNoScore, Reason: "Lint errored"}, -1, 2, "No score: Lint errored."},
		{"no score without a reason", &api.CommitScore{Outcome: api.OutcomeEnumNoScore}, -1, 2, "No score: not every standard has a result on this commit."},
		{"failed", &api.CommitScore{Outcome: api.OutcomeEnumFailed, Reason: "No secrets failing"}, -1, 1, "Failed: No secrets failing."},
		{"failed ignores --fail-under", &api.CommitScore{Outcome: api.OutcomeEnumFailed, Reason: "X failing"}, 0, 1, "Failed: X failing."},
		{"scored", &api.CommitScore{Outcome: api.OutcomeEnumScored, Value: value(80)}, -1, 0, ""},
		{"scored 0 is a score", &api.CommitScore{Outcome: api.OutcomeEnumScored, Value: value(0)}, -1, 0, ""},
		{"scored at --fail-under", &api.CommitScore{Outcome: api.OutcomeEnumScored, Value: value(80)}, 80, 0, ""},
		{"scored under --fail-under", &api.CommitScore{Outcome: api.OutcomeEnumScored, Value: value(79)}, 80, 1, "Score 79 is under 80."},
		{"scored with no value", &api.CommitScore{Outcome: api.OutcomeEnumScored}, -1, 2, "No score: the commit has no value."},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			code, why := verdict(&api.Commit{CommitScore: c.score}, c.failUnder)
			if code != c.code || why != c.why {
				t.Errorf("verdict = (%d, %q); want (%d, %q)", code, why, c.code, c.why)
			}
		})
	}
}

func TestCheckWaitWithoutShaRecommendsIt(t *testing.T) {
	out, _ := runCLI(t, fakeAPI(t, 0, nil), "check", "-p", "acme/api", "--branch", "main", "--wait")
	if !strings.Contains(out, "Tip: pass --sha") {
		t.Errorf("no --sha tip:\n%s", out)
	}
}

func TestCheckWaitFailUnder(t *testing.T) {
	s := sha
	// One of two failed: score 50.
	if _, err := runCLI(t, fakeAPI(t, 1, &s), "check", "-p", "acme/api", "--sha", sha, "--wait", "--fail-under", "50"); exitCode(err) != 0 {
		t.Errorf("score 50 with --fail-under 50: exit %d; want 0", exitCode(err))
	}
	if _, err := runCLI(t, fakeAPI(t, 1, &s), "check", "-p", "acme/api", "--sha", sha, "--wait", "--fail-under", "51"); exitCode(err) != 1 {
		t.Errorf("score 50 with --fail-under 51: exit %d; want 1", exitCode(err))
	}
}

func TestCheckWaitWithoutAPinnedCommitFollowsTheBranch(t *testing.T) {
	out, err := runCLI(t, fakeAPI(t, 0, nil), "check", "-p", "acme/api", "--branch", "main", "--wait")
	if exitCode(err) != 0 || !strings.Contains(out, "2 passed") {
		t.Fatalf("exit %d; output:\n%s", exitCode(err), out)
	}
}

func TestCheckWaitJSON(t *testing.T) {
	s := sha
	out, err := runCLI(t, fakeAPI(t, 0, &s), "check", "-p", "acme/api", "--sha", sha, "--wait", "--json")
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if json.Unmarshal([]byte(out), &got) != nil || got["sha"] != sha {
		t.Errorf("--json output is not the commit:\n%s", out)
	}
}
