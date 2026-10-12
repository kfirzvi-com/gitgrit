package cmd

import (
	"fmt"
	"os"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/gitctx"
)

func newValidateCmd() *cobra.Command {
	var project string
	cmd := &cobra.Command{
		Use:   "validate <file>",
		Short: "Check a local edit against the project's standards before committing",
		Long: `Compare a file in your working copy with its committed version and report
violations the edit introduces. Exits 1 when it introduces any — usable from a
pre-commit hook or an AI agent's edit hook. Only locally enforceable rules are
checked; GitGrit's sandbox stays authoritative on the next push.`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			path := args[0]
			current, err := os.ReadFile(path)
			if err != nil {
				return err
			}
			body := api.ValidateEditRequest{FilePath: gitctx.RepoPath(path), NewContent: string(current)}
			if prior, ok := gitctx.FileAtHead(path); ok {
				body.PriorContent = &prior
			}
			resp, err := t.s.API.ValidateEditWithResponse(cmd.Context(), t.ws.ID, t.p.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			r := resp.JSON200
			if err := emit(cmd.OutOrStdout(), resp.Body, func() {
				w := cmd.OutOrStdout()
				if r.Allowed {
					fmt.Fprintf(w, "✓ %s: no new violations (%d standards checked, %d not applicable)\n", path, r.Checked, r.Skipped)
				} else {
					fmt.Fprintf(w, "✗ %s introduces %d violation(s):\n", path, len(r.IntroducedViolations))
					for _, v := range r.IntroducedViolations {
						fmt.Fprintf(w, "  %s: %s %q\n    %s\n", v.Standard, v.Kind, v.Value, v.Snippet)
					}
				}
				if r.PreExistingViolationsCount > 0 {
					fmt.Fprintf(w, "(%d violation(s) were already there before this edit.)\n", r.PreExistingViolationsCount)
				}
				for _, n := range r.Notes {
					fmt.Fprintln(w, "note:", n)
				}
			}); err != nil {
				return err
			}
			if !r.Allowed {
				return &ExitError{Code: 1}
			}
			return nil
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	return cmd
}
