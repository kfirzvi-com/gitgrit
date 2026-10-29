package cmd

import (
	"errors"
	"fmt"
	"strings"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/gitctx"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newProjectCmd() *cobra.Command {
	c := &cobra.Command{Use: "project", Aliases: []string{"projects"}, Short: "Add, list and manage projects"}
	c.AddCommand(projectAdd(), projectEdit(), projectRemove(), projectStandards(), projectAttach(), projectDetach())
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
	c.AddCommand(view, newProjectUploadCmd())
	return c
}

func projectAdd() *cobra.Command {
	var connection, lifecycle, owner string
	var standards []string
	var allStandards bool
	var artifact artifactFlags
	cmd := &cobra.Command{
		Use:   "add [org/repo]",
		Short: "Add a repository as a project (default: this repository), or an artifact project",
		Long: "Add a repository as a project. Without an argument, adds the git repository\n" +
			"in the current directory (its origin remote).\n\n" +
			"No standards are attached unless you pass --standard or --all-standards;\n" +
			"attached standards run once right away, then on every push.\n\n" +
			"With --artifact, create an artifact project instead: one whose commits are\n" +
			"build archives you upload (gitgrit project upload). Adding it again with the\n" +
			"same --external-id returns the existing project; without --standard it gets\n" +
			"every published standard that runs on uploads.",
		Example: "  gitgrit project add acme/api --all-standards\n" +
			"  gitgrit project add --standard \"README Exists\" --standard \"License File\"\n" +
			"  gitgrit project add --artifact --name Storefront --stack \"Web Team\"",
		Args: cobra.MaximumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if artifact.on {
				if len(args) > 0 {
					return errors.New("an artifact project has no repository; drop the org/repo argument")
				}
				return addArtifactProject(cmd, artifact, standards, allStandards)
			}
			repo := ""
			if len(args) == 1 {
				repo = args[0]
			} else {
				remote := gitctx.OriginURL()
				if remote == "" {
					return errors.New("not in a git repository with an `origin` remote; pass org/repo")
				}
				if repo = gitctx.FullPath(remote); repo == "" {
					return fmt.Errorf("can't tell the repository from origin %q; pass org/repo", gitctx.SafeRemote(remote))
				}
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			body := api.ProjectCreateRequest{Repository: &repo, Lifecycle: &lifecycle, Owner: &owner}
			if connection != "" {
				c, err := connectionFor(cmd, t, connection)
				if err != nil {
					return err
				}
				body.ConnectionId = &c.Id
			}
			ids, err := standardIDs(cmd, t, standards, allStandards)
			if err != nil {
				return err
			}
			body.Standards = &ids
			resp, err := t.s.API.CreateProjectWithResponse(cmd.Context(), t.ws.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				p, w := resp.JSON201, cmd.OutOrStdout()
				fmt.Fprintf(w, "Added %s (%s).\n", p.FullPath, p.Id)
				if p.Webhook == api.Missing {
					fmt.Fprintln(w, "Warning: the webhook couldn't be registered, so pushes won't trigger checks. Retry from the project page.")
				}
				if p.Runs != nil {
					fmt.Fprintln(w, p.Runs.Message)
					fmt.Fprintln(w, "Then: gitgrit health --project "+p.FullPath)
				} else if len(p.Standards) == 0 {
					fmt.Fprintln(w, "No standards attached, so nothing will run. Attach some: gitgrit project attach --project "+p.FullPath+" <standard>…")
				}
			})
		},
	}
	f := cmd.Flags()
	f.StringVarP(&connection, "connection", "c", "", "connection id or name (default: the one that reaches the repository)")
	f.StringVar(&lifecycle, "lifecycle", "development", "development, staging, production, maintenance, deprecated or archived")
	f.StringVar(&owner, "owner", "", "owning team or person")
	f.StringArrayVarP(&standards, "standard", "s", nil, "standard to attach, by name or id (repeatable)")
	f.BoolVar(&allStandards, "all-standards", false, "attach every enabled standard in the workspace")
	cmd.MarkFlagsMutuallyExclusive("standard", "all-standards")
	artifact.register(f)
	return cmd
}

func projectEdit() *cobra.Command {
	var project, lifecycle, owner string
	cmd := &cobra.Command{
		Use:   "edit",
		Short: "Change a project's lifecycle or owner",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			f := cmd.Flags()
			if !f.Changed("lifecycle") && !f.Changed("owner") {
				return errors.New("nothing to change; pass --lifecycle and/or --owner")
			}
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			body := api.UpdateProjectJSONRequestBody{}
			if f.Changed("lifecycle") {
				body.Lifecycle = &lifecycle
			}
			if f.Changed("owner") {
				body.Owner = &owner
			}
			resp, err := t.s.API.UpdateProjectWithResponse(cmd.Context(), t.ws.ID, t.p.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				p := resp.JSON200
				fmt.Fprintf(cmd.OutOrStdout(), "Updated %s: lifecycle %s, owner %q.\n", p.FullPath, p.Lifecycle, p.Owner)
			})
		},
	}
	f := cmd.Flags()
	f.StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	f.StringVar(&lifecycle, "lifecycle", "", "development, staging, production, maintenance, deprecated or archived")
	f.StringVar(&owner, "owner", "", "owning team or person (empty clears it)")
	return cmd
}

func projectRemove() *cobra.Command {
	var project string
	var yes bool
	cmd := &cobra.Command{
		Use:     "remove",
		Aliases: []string{"rm", "delete"},
		Short:   "Remove a project from the workspace",
		Args:    cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if !yes {
				return errors.New("removing a project deletes its results and can't be undone; pass --yes to confirm")
			}
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			resp, err := t.s.API.DeleteProjectWithResponse(cmd.Context(), t.ws.ID, t.p.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			if !jsonFlag {
				fmt.Fprintln(cmd.OutOrStdout(), "Removed.")
			}
			return nil
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "confirm the removal")
	return cmd
}

func projectStandards() *cobra.Command {
	var project string
	cmd := &cobra.Command{
		Use:   "standards",
		Short: "List the standards attached to a project",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetProjectWithResponse(cmd.Context(), t.ws.ID, t.p.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				printAttached(cmd, resp.JSON200.Standards, nil)
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	return cmd
}

func projectAttach() *cobra.Command {
	var project string
	var all bool
	cmd := &cobra.Command{
		Use:   "attach <standard>...",
		Short: "Attach standards to a project; they run on it right away",
		Example: "  gitgrit project attach \"README Exists\" \"License File\"\n" +
			"  gitgrit project attach --all --project acme/api",
		RunE: func(cmd *cobra.Command, args []string) error {
			if len(args) == 0 && !all {
				return errors.New("name the standards to attach (by name or id), or pass --all")
			}
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			ids, err := standardIDs(cmd, t, args, all)
			if err != nil {
				return err
			}
			resp, err := t.s.API.AttachProjectStandardsWithResponse(cmd.Context(), t.ws.ID, t.p.ID, api.StandardIdsRequest{Standards: ids})
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				printAttached(cmd, resp.JSON200.Standards, resp.JSON200.Runs)
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	cmd.Flags().BoolVar(&all, "all", false, "attach every enabled standard in the workspace")
	return cmd
}

func projectDetach() *cobra.Command {
	var project string
	cmd := &cobra.Command{
		Use:   "detach <standard>...",
		Short: "Detach standards from a project",
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, true)
			if err != nil {
				return err
			}
			ids, err := standardIDs(cmd, t, args, false)
			if err != nil {
				return err
			}
			var last *api.DetachProjectStandardResponse
			for _, id := range ids {
				if last, err = t.s.API.DetachProjectStandardWithResponse(cmd.Context(), t.ws.ID, t.p.ID, id); err != nil {
					return err
				}
				if err := checkResp(last.HTTPResponse, last.Body); err != nil {
					return err
				}
			}
			return emit(cmd.OutOrStdout(), last.Body, func() {
				printAttached(cmd, last.JSON200.Standards, nil)
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "project id or org/repo (default: this repository)")
	return cmd
}

func printAttached(cmd *cobra.Command, standards []api.AttachedStandard, runs *api.RunsSummary) {
	w := cmd.OutOrStdout()
	if len(standards) == 0 {
		fmt.Fprintln(w, "No standards attached.")
	} else {
		tb := output.NewTable(w, "ATTACHED STANDARD", "STATE", "ID")
		for _, s := range standards {
			tb.Row(s.Name, standardState(s.Enabled, s.Draft), s.Id.String())
		}
		tb.Flush()
	}
	if runs != nil {
		fmt.Fprintln(w, runs.Message)
	}
}
