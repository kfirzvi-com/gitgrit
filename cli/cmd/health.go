package cmd

import (
	"fmt"
	"io"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/gitctx"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func printResults(w io.Writer, results []api.CheckResult) {
	if len(results) == 0 {
		fmt.Fprintln(w, "No results yet.")
		return
	}
	t := output.NewTable(w, "STATUS", "SCORE", "STANDARD", "COMMIT", "RAN", "MESSAGE")
	for _, r := range results {
		msg := r.Message
		if len(msg) > 60 {
			msg = msg[:59] + "…"
		}
		t.Row(output.Status(string(r.Status)), output.Score(r.Score), r.StandardName, output.Short(r.CommitSha), output.Ago(r.RanAt), msg)
	}
	t.Flush()
}

// summary leads with the grade as the app shows it ("B", "F"), so a failed
// project reads F, never a number, then its health (display.tone).
func summary(display api.ScoreDisplay, passed, failed, errored int) string {
	return fmt.Sprintf("Grade %s · %s · %d passed, %d failed, %d errored", display.Text, display.Tone, passed, failed, errored)
}

func newHealthCmd() *cobra.Command {
	var project, branch string
	cmd := &cobra.Command{
		Use:   "health",
		Short: "Show a project's health, or a branch's",
		Long: `Show a project's health: each attached standard's latest result on its home
branch (the default branch, unless the standard names another). With --branch,
show that branch's own health instead.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			params := &api.GetProjectHealthParams{}
			if branch != "" {
				params.Branch = &branch
			}
			resp, err := t.s.API.GetProjectHealthWithResponse(cmd.Context(), t.ws.ID, t.p.ID, params)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				h, w := resp.JSON200, cmd.OutOrStdout()
				scope := "project health"
				if h.Branch != nil {
					scope = "branch " + *h.Branch
				}
				fmt.Fprintf(w, "%s · %s\n%s\n", h.Project.Name, scope, summary(h.ScoreDisplay, h.Passed, h.Failed, h.Errored))
				if h.Running {
					fmt.Fprintln(w, "Checks are running…")
				}
				fmt.Fprintln(w)
				printResults(w, h.Results)
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	cmd.Flags().StringVarP(&branch, "branch", "b", "", "show this branch's health")
	return cmd
}

func newBranchesCmd() *cobra.Command {
	var project string
	cmd := &cobra.Command{
		Use:   "branches",
		Short: "List a project's branches",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListProjectBranchesWithResponse(cmd.Context(), t.ws.ID, t.p.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				for _, b := range *resp.JSON200 {
					if b.IsDefault {
						fmt.Fprintf(cmd.OutOrStdout(), "%s (default)\n", b.Name)
					} else {
						fmt.Fprintln(cmd.OutOrStdout(), b.Name)
					}
				}
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	return cmd
}

func newCommitsCmd() *cobra.Command {
	var project, branch string
	var page int
	cmd := &cobra.Command{
		Use:   "commits",
		Short: "List a branch's commits with their checks",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			params := &api.ListProjectCommitsParams{Page: &page}
			if branch != "" {
				params.Branch = &branch
			}
			resp, err := t.s.API.ListProjectCommitsWithResponse(cmd.Context(), t.ws.ID, t.p.ID, params)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				pg, w := resp.JSON200, cmd.OutOrStdout()
				fmt.Fprintf(w, "%s · %s · page %d\n\n", t.p.Name, pg.Branch, pg.Page)
				tb := output.NewTable(w, "COMMIT", "SCORE", "CHECKS", "WHEN", "AUTHOR", "TITLE")
				for _, c := range pg.Commits {
					checks := "not checked"
					if c.Checked {
						checks = fmt.Sprintf("%d✓ %d✗ %d!", c.Passed, c.Failed, c.Errored)
						if c.Running > 0 {
							checks += fmt.Sprintf(" %d…", c.Running)
						}
					}
					when := "—"
					if c.Date != nil {
						when = output.Ago(*c.Date)
					}
					tb.Row(output.Short(c.Sha), output.Score(c.Score), checks, when, c.Author, c.Title)
				}
				tb.Flush()
				if pg.HasMore {
					fmt.Fprintf(w, "\nOlder commits: --page %d\n", pg.Page+1)
				}
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	cmd.Flags().StringVarP(&branch, "branch", "b", "", "branch (default: the project's default branch)")
	cmd.Flags().IntVar(&page, "page", 1, "page of 5 commits")
	return cmd
}

func newCommitCmd() *cobra.Command {
	var project string
	cmd := &cobra.Command{
		Use:   "commit <sha>",
		Short: "Show one commit's checks",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetProjectCommitWithResponse(cmd.Context(), t.ws.ID, t.p.ID, gitctx.FullSHA(args[0]))
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() { printCommit(cmd.OutOrStdout(), resp.JSON200) })
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	return cmd
}

func printCommit(w io.Writer, c *api.Commit) {
	header := output.Short(c.Sha)
	if c.Title != "" {
		header += " " + c.Title
	}
	fmt.Fprintf(w, "%s\n%s\n", header, summary(c.ScoreDisplay, c.Passed, c.Failed, c.Errored))
	if c.Running > 0 {
		fmt.Fprintf(w, "%d still running…\n", c.Running)
	}
	fmt.Fprintln(w)
	printResults(w, c.Results)
	if len(c.ExpectedButNeverRan) > 0 {
		fmt.Fprintln(w, "\nExpected, never ran on this commit:")
		for _, s := range c.ExpectedButNeverRan {
			fmt.Fprintf(w, "  %s\n", s.Name)
		}
	}
}
