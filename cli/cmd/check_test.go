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
)

const (
	wsID   = "0b0f1c2e-3d4a-4b5c-8d9e-0f1a2b3c4d5e"
	projID = "11111111-2222-3333-4444-555555555555"
	sha    = "cccccccccccccccccccccccccccccccccccccccc"
)

// fakeAPI serves the endpoints `check --wait` uses. The commit reports
// "running" for the first polls, then the given final result: ``failed``
// of two standards failed, scored as the server would (``state`` and a
// failing Required standard set by the variants below).
func fakeAPI(t *testing.T, failed int, commitSHA *string) *httptest.Server {
	return fakeAPIWith(t, failed, commitSHA, "complete", false)
}

func fakeAPIWith(t *testing.T, failed int, commitSHA *string, state string, requiredFailed bool) *httptest.Server {
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
		reason := ""
		if requiredFailed {
			score, reason = 0, "No secrets failing"
		}
		if state != "complete" {
			score = nil
		}
		return map[string]any{
			"sha": sha, "title": "Fix", "author": "Dana", "date": nil, "url": "", "checked": true, "running": running,
			"score": score, "level": "healthy", "passed": 2 - failed, "failed": failed, "errored": 0,
			"commit_score": map[string]any{
				"value": score, "failed": requiredFailed, "reason": reason, "state": state,
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
	out, err := runCLI(t, fakeAPIWith(t, 1, &s, "complete", true), "check", "-p", "acme/api", "--sha", sha, "--wait")
	if exitCode(err) != 1 || !strings.Contains(out, "Failed: No secrets failing.") {
		t.Fatalf("exit %d; want 1 with the reason; output:\n%s", exitCode(err), out)
	}
}

func TestCheckWaitExitsTwoWithoutAScore(t *testing.T) {
	s := sha
	out, err := runCLI(t, fakeAPIWith(t, 0, &s, "incomplete", false), "check", "-p", "acme/api", "--sha", sha, "--wait")
	if exitCode(err) != 2 || !strings.Contains(out, "No score") {
		t.Fatalf("exit %d; want 2; output:\n%s", exitCode(err), out)
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
