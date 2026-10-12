package cmd

import (
	"fmt"
	"strings"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newProjectCmd() *cobra.Command {
	c := &cobra.Command{Use: "project", Aliases: []string{"projects"}, Short: "List and find projects"}
	c.AddCommand(&cobra.Command{
		Use:   "list",
		Short: "List the workspace's projects",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListProjectsWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				tb := output.NewTable(cmd.OutOrStdout(), "PROJECT", "PLATFORM", "DEFAULT BRANCH", "LANGUAGES", "ID")
				for _, p := range *resp.JSON200 {
					tb.Row(p.FullPath, p.Platform, p.DefaultBranch, strings.Join(p.Languages, ", "), p.Id.String())
				}
				tb.Flush()
			})
		},
	})
	var project string
	view := &cobra.Command{
		Use:   "view",
		Short: "Show which project this repository (or --project) is",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			params := &api.ResolveProjectParams{}
			p, err := t.s.Project(cmd.Context(), t.ws, project)
			if err != nil {
				return err
			}
			params.RepoFullPath = &p.FullPath
			if p.FullPath == "" { // --project was an id
				fmt.Fprintln(cmd.OutOrStdout(), p.ID)
				return nil
			}
			resp, err := t.s.API.ResolveProjectWithResponse(cmd.Context(), t.ws.ID, params)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				r := resp.JSON200
				fmt.Fprintf(cmd.OutOrStdout(), "%s (%s)\n  id: %s\n  default branch: %s\n  url: %s\n",
					r.FullPath, r.Platform, r.Id, r.DefaultBranch, r.WebUrl)
			})
		},
	}
	view.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	c.AddCommand(view)
	return c
}
