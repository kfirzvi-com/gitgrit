package cmd

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"time"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/gitctx"
)

// pollEvery is how often `check --wait` asks for results.
var pollEvery = 3 * time.Second

func newCheckCmd() *cobra.Command {
	var project, branch, sha string
	var wait bool
	var timeout time.Duration
	var failUnder int
	cmd := &cobra.Command{
		Use:   "check",
		Short: "Check a commit against the project's standards",
		Long: `Run the standards that apply to a branch, on one commit or on the branch's
latest commit. With --wait, wait for the results and exit non-zero when any
standard fails or errors (or the score is under --fail-under) — for CI:

  gitgrit check --branch "$GITHUB_REF_NAME" --sha "$GITHUB_SHA" --wait

Inside a git repository the branch defaults to the checked-out one.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			t, err := resolve(ctx, project, true)
			if err != nil {
				return err
			}
			if branch == "" && project == "" {
				branch = gitctx.CurrentBranch()
			}
			body := api.RunCheckRequest{}
			if branch != "" {
				body.Branch = &branch
			}
			if sha != "" {
				full := gitctx.FullSHA(sha)
				body.Sha = &full
			}
			resp, err := t.s.API.RunProjectCheckWithResponse(ctx, t.ws.ID, t.p.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			run := resp.JSON202
			if !wait {
				return emit(cmd.OutOrStdout(), resp.Body, func() { fmt.Fprintln(cmd.OutOrStdout(), run.Message) })
			}
			if !jsonFlag {
				fmt.Fprintln(cmd.ErrOrStderr(), run.Message)
			}
			if run.Queued == 0 && run.AlreadyRunning == 0 {
				return nil // nothing applies to the branch
			}
			ctx, cancel := context.WithTimeout(ctx, timeout)
			defer cancel()
			var commit *api.Commit
			var raw []byte
			if run.CommitSha != nil {
				commit, raw, err = waitForCommit(ctx, t, *run.CommitSha)
			} else {
				commit, raw, err = waitForBranchHead(ctx, t, run.Branch)
			}
			if err != nil {
				return err
			}
			if err := emit(cmd.OutOrStdout(), raw, func() {
				fmt.Fprintln(cmd.OutOrStdout())
				printCommit(cmd.OutOrStdout(), commit)
			}); err != nil {
				return err
			}
			return verdict(commit, failUnder)
		},
	}
	f := cmd.Flags()
	f.StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	f.StringVarP(&branch, "branch", "b", "", "branch (default: the checked-out one, else the project's default)")
	f.StringVar(&sha, "sha", "", "commit to check (default: the branch's latest)")
	f.BoolVar(&wait, "wait", false, "wait for results; exit 1 if any standard fails or errors")
	f.DurationVar(&timeout, "timeout", 15*time.Minute, "how long --wait waits")
	f.IntVar(&failUnder, "fail-under", -1, "with --wait, fail only when the score is under this (0-100) instead of on any failure")
	return cmd
}

// verdict turns finished results into the exit code.
func verdict(c *api.Commit, failUnder int) error {
	if failUnder >= 0 {
		if c.Score != nil && *c.Score < failUnder {
			return &ExitError{Code: 1}
		}
		return nil
	}
	if c.Failed > 0 || c.Errored > 0 {
		return &ExitError{Code: 1}
	}
	return nil
}

func waitForCommit(ctx context.Context, t *target, sha string) (*api.Commit, []byte, error) {
	for {
		resp, err := t.s.API.GetProjectCommitWithResponse(ctx, t.ws.ID, t.p.ID, sha)
		if err != nil {
			return nil, nil, waitErr(ctx, err)
		}
		switch {
		case resp.StatusCode() == http.StatusNotFound:
			// Not recorded yet: keep waiting.
		case resp.JSON200 != nil && resp.JSON200.Running == 0:
			return resp.JSON200, resp.Body, nil
		default:
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return nil, nil, err
			}
		}
		if err := sleep(ctx); err != nil {
			return nil, nil, err
		}
	}
}

// waitForBranchHead covers a check queued before the server could tell which
// commit the branch's head is: the job pins it, so wait for the newest checked
// commit on the branch to finish.
func waitForBranchHead(ctx context.Context, t *target, branch string) (*api.Commit, []byte, error) {
	page := 1
	params := &api.ListProjectCommitsParams{Branch: &branch, Page: &page}
	for {
		resp, err := t.s.API.ListProjectCommitsWithResponse(ctx, t.ws.ID, t.p.ID, params)
		if err != nil {
			return nil, nil, waitErr(ctx, err)
		}
		if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
			return nil, nil, err
		}
		for _, c := range resp.JSON200.Commits {
			if c.Checked {
				if c.Running == 0 {
					raw, _ := json.Marshal(c)
					return &c, raw, nil
				}
				break
			}
		}
		if err := sleep(ctx); err != nil {
			return nil, nil, err
		}
	}
}

func sleep(ctx context.Context) error {
	select {
	case <-time.After(pollEvery):
		return nil
	case <-ctx.Done():
		return waitErr(ctx, ctx.Err())
	}
}

func waitErr(ctx context.Context, err error) error {
	if errors.Is(ctx.Err(), context.DeadlineExceeded) {
		return errors.New("timed out waiting for the checks; see them later with `gitgrit commits`")
	}
	return err
}
