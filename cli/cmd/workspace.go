package cmd

import (
	"fmt"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newWorkspaceCmd() *cobra.Command {
	c := &cobra.Command{Use: "workspace", Aliases: []string{"ws"}, Short: "List workspaces and pick the default"}
	c.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List the workspaces you can use",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			resp, err := s.API.GetMeWithResponse(cmd.Context())
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			current := ""
			if h := s.HostConfig(); h != nil && !s.UsingEnvToken() {
				current = h.Workspace
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				t := output.NewTable(cmd.OutOrStdout(), "", "NAME", "ROLE", "ID")
				for _, w := range resp.JSON200.Workspaces {
					mark, role := "", "—"
					if w.Id.String() == current {
						mark = "*"
					}
					if w.Role != nil {
						role = *w.Role
					}
					t.Row(mark, w.Name, role, w.Id.String())
				}
				t.Flush()
			})
		},
	})
	c.AddCommand(&cobra.Command{
		Use:   "use <name-or-id>",
		Short: "Set the default workspace for this instance",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			if s.UsingEnvToken() {
				return fmt.Errorf("GITGRIT_TOKEN is set; use --workspace or GITGRIT_WORKSPACE instead")
			}
			me, err := s.Me(cmd.Context())
			if err != nil {
				return err
			}
			for _, w := range me.Workspaces {
				if w.Id.String() == args[0] || equalFold(w.Name, args[0]) {
					h := s.Config.Host(s.Host)
					h.Workspace, h.WorkspaceName = w.Id.String(), w.Name
					if err := s.Config.Save(); err != nil {
						return err
					}
					fmt.Fprintf(cmd.OutOrStdout(), "Using workspace %s on %s.\n", w.Name, s.Host)
					return nil
				}
			}
			return fmt.Errorf("no workspace %q; see `gitgrit workspace list`", args[0])
		},
	})
	return c
}
