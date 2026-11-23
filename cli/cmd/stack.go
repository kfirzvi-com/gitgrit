package cmd

import (
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newStackCmd() *cobra.Command {
	c := &cobra.Command{
		Use:     "stack",
		Aliases: []string{"stacks"},
		Short:   "Stacks and their health",
		Long: "A stack groups projects. A monorepo's projects (one per app or service,\n" +
			"each at its own path) can sit in different stacks.",
	}
	c.AddCommand(stackList(), stackView(), stackCreate(), stackEdit(), stackDelete(),
		stackAdd(), stackRemove(), stackRefresh())
	return c
}

func stackList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "Stacks, each with its projects counted by health (worst first)",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListStacksWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				if len(*resp.JSON200) == 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "No stacks yet.")
					return
				}
				tb := output.NewTable(cmd.OutOrStdout(), "STACK", "PROJECTS", "FAILED", "NEED ATTENTION", "HEALTHY", "ID")
				for _, s := range *resp.JSON200 {
					tb.Row(s.Name, fmt.Sprint(s.ProjectCount), fmt.Sprint(s.Failed), fmt.Sprint(s.NeedsAttention), fmt.Sprint(s.Healthy), s.Id.String())
				}
				tb.Flush()
			})
		},
	}
}

func stackView() *cobra.Command {
	return &cobra.Command{
		Use:   "view <stack>",
		Short: "A stack's health and its projects, worst first",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			id, err := stackID(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetStackWithResponse(cmd.Context(), t.ws.ID, id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				w, s := cmd.OutOrStdout(), resp.JSON200
				fmt.Fprintf(w, "%s: %d projects: %d failed · %d need attention · %d healthy · %d standards\n",
					s.Name, s.ProjectCount, s.Failed, s.NeedsAttention, s.Healthy, s.StandardCount)
				switch {
				case s.MapRefreshing:
					fmt.Fprintln(w, "Map: refreshing…")
				case s.MapUpdatedAt != nil:
					fmt.Fprintf(w, "Map: updated %s\n", output.Ago(*s.MapUpdatedAt))
				}
				if len(s.Projects) == 0 {
					fmt.Fprintln(w, "\nNo projects yet.")
					return
				}
				fmt.Fprintln(w)
				tb := output.NewTable(w, "PROJECT", "REPOSITORY", "HEALTH", "GRADE", "WHY", "CHECKED")
				for _, p := range s.Projects {
					checked := "—"
					if p.LastChecked != nil {
						checked = output.Ago(*p.LastChecked)
					}
					tb.Row(p.Name, dash(projectLabel(p.FullPath, p.RootPath)), tone(p.Tone), grade(p.Grade), dash(p.Why), checked)
				}
				tb.Flush()
			})
		},
	}
}

func stackRefresh() *cobra.Command {
	return &cobra.Command{
		Use:   "refresh <stack>",
		Short: "Rebuild a stack's map from its projects' main branches (superusers)",
		Long:  "Queued: the worker reads each project. It costs one LLM run per project.",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			id, err := stackID(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.RefreshStackMapWithResponse(cmd.Context(), t.ws.ID, id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				n := resp.JSON202.Queued
				if n == 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "No projects to refresh.")
					return
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Refreshing the map from the main branch of %d project%s.\n", n, plural(n))
			})
		},
	}
}

func stackCreate() *cobra.Command {
	var description string
	cmd := &cobra.Command{
		Use:     "create <name>",
		Short:   "Create a stack",
		Example: "  gitgrit stack create Payments --description \"Checkout and billing\"\n  gitgrit stack add Payments acme/checkout acme/mono#services/billing",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.CreateStackWithResponse(cmd.Context(), t.ws.ID, api.StackCreateRequest{Name: args[0], Description: &description})
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				fmt.Fprintf(cmd.OutOrStdout(), "Created %s (%s).\nNext: gitgrit stack add %q <project>…\n", resp.JSON201.Name, resp.JSON201.Id, resp.JSON201.Name)
			})
		},
	}
	cmd.Flags().StringVar(&description, "description", "", "what the stack is")
	return cmd
}

func stackEdit() *cobra.Command {
	var name, description string
	cmd := &cobra.Command{
		Use:   "edit <stack>",
		Short: "Rename a stack or change its description",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			body := api.PatchedStackUpdateRequest{}
			if cmd.Flags().Changed("name") {
				body.Name = &name
			}
			if cmd.Flags().Changed("description") {
				body.Description = &description
			}
			if body.Name == nil && body.Description == nil {
				return errors.New("nothing to change; pass --name or --description")
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			id, err := stackID(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.UpdateStackWithResponse(cmd.Context(), t.ws.ID, id, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				fmt.Fprintf(cmd.OutOrStdout(), "Updated %s.\n", resp.JSON200.Name)
			})
		},
	}
	cmd.Flags().StringVar(&name, "name", "", "new name")
	cmd.Flags().StringVar(&description, "description", "", "new description")
	return cmd
}

func stackDelete() *cobra.Command {
	var yes bool
	cmd := &cobra.Command{
		Use:     "delete <stack>",
		Aliases: []string{"rm"},
		Short:   "Delete a stack (its projects stay; only the grouping goes)",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if !yes {
				return errors.New("deleting a stack can't be undone; pass --yes to confirm")
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			id, err := stackID(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.DeleteStackWithResponse(cmd.Context(), t.ws.ID, id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Deleted %s.\n", args[0])
			return nil
		},
	}
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "confirm the deletion")
	return cmd
}

const projectHelp = "A project is its id, its repository (org/repo: the whole-repository project),\n" +
	"org/repo#path (a monorepo project; org/repo:path works too), or its name.\n" +
	"With none, the project of the current directory."

func stackAdd() *cobra.Command {
	return &cobra.Command{
		Use:     "add <stack> [project…]",
		Short:   "Add projects to a stack",
		Long:    "Add projects to a stack.\n\n" + projectHelp,
		Example: "  gitgrit stack add Payments                       # this project\n  gitgrit stack add Payments acme/checkout acme/mono#services/billing",
		Args:    cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, stack, projects, err := stackAndProjects(cmd, args)
			if err != nil {
				return err
			}
			var ids []uuid.UUID
			seen := map[uuid.UUID]bool{}
			for _, p := range projects {
				if !seen[p.Id] {
					seen[p.Id] = true
					ids = append(ids, p.Id)
				}
			}
			resp, err := t.s.API.AddStackProjectsWithResponse(cmd.Context(), t.ws.ID, stack, api.ProjectIdsRequest{ProjectIds: ids})
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				n := resp.JSON200.Added
				fmt.Fprintf(cmd.OutOrStdout(), "Added %d project%s to %s", n, plural(n), args[0])
				if skipped := len(ids) - n; skipped > 0 {
					fmt.Fprintf(cmd.OutOrStdout(), " (%d already in it)", skipped)
				}
				fmt.Fprintln(cmd.OutOrStdout(), ".")
			})
		},
	}
}

func stackRemove() *cobra.Command {
	return &cobra.Command{
		Use:   "remove <stack> [project…]",
		Short: "Take projects out of a stack",
		Long:  "Take projects out of a stack.\n\n" + projectHelp,
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, stack, projects, err := stackAndProjects(cmd, args)
			if err != nil {
				return err
			}
			for _, p := range projects {
				resp, err := t.s.API.RemoveStackProjectWithResponse(cmd.Context(), t.ws.ID, stack, p.Id)
				if err != nil {
					return err
				}
				if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
					return fmt.Errorf("%s: %w", projectRef(p), err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Removed %s from %s.\n", projectRef(p), args[0])
			}
			return nil
		},
	}
}

// stackAndProjects resolves `<stack> [project…]`; no project means the one
// the current directory is in.
func stackAndProjects(cmd *cobra.Command, args []string) (*target, uuid.UUID, []api.Project, error) {
	refs := args[1:]
	t, err := resolve(cmd.Context(), "", len(refs) == 0)
	if err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	stack, err := stackID(cmd, t, args[0])
	if err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	resp, err := t.s.API.ListProjectsWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	if len(refs) == 0 {
		refs = []string{t.p.ID.String()}
	}
	projects, err := findProjects(*resp.JSON200, refs)
	return t, stack, projects, err
}

// findProjects resolves each ref: a project id; org/repo for the
// whole-repository project; org/repo#path or org/repo:path for one inside a
// monorepo; or a project name.
func findProjects(all []api.Project, refs []string) ([]api.Project, error) {
	out := make([]api.Project, 0, len(refs))
	for _, ref := range refs {
		var match []api.Project
		repo, path, hasPath := strings.Cut(ref, "#")
		if !hasPath {
			repo, path, hasPath = strings.Cut(ref, ":")
		}
		id, idErr := uuid.Parse(ref)
		for _, p := range all {
			sameRepo := equalFold(p.FullPath, repo)
			switch {
			case idErr == nil && p.Id == id:
				match = append(match, p)
			case sameRepo && strings.Trim(p.RootPath, "/") == strings.Trim(path, "/") && (hasPath || p.RootPath == ""):
				match = append(match, p)
			case !hasPath && idErr != nil && !sameRepo && equalFold(p.Name, ref):
				match = append(match, p)
			}
		}
		switch len(match) {
		case 0:
			return nil, fmt.Errorf("no project %q; see `gitgrit project list`", ref)
		case 1:
			out = append(out, match[0])
		default:
			labels := make([]string, len(match))
			for i, p := range match {
				labels[i] = projectRef(p)
			}
			return nil, fmt.Errorf("%q could be %s; name it as org/repo#path", ref, strings.Join(labels, ", "))
		}
	}
	return out, nil
}

// projectRef is how a project is named on the command line: org/repo for a
// whole-repository project, org/repo#path for one inside a monorepo, its
// name for an artifact project.
func projectRef(p api.Project) string {
	repo := p.FullPath
	if repo == "" {
		repo = p.Name
	}
	if p.RootPath == "" {
		return repo
	}
	return repo + "#" + p.RootPath
}

func plural(n int) string {
	if n == 1 {
		return ""
	}
	return "s"
}

// stackID finds a stack by id or name.
func stackID(cmd *cobra.Command, t *target, ref string) (uuid.UUID, error) {
	if id, err := uuid.Parse(ref); err == nil {
		return id, nil
	}
	resp, err := t.s.API.ListStacksWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return uuid.UUID{}, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return uuid.UUID{}, err
	}
	return findStack(*resp.JSON200, ref)
}

func findStack(stacks []api.StackSummary, ref string) (uuid.UUID, error) {
	var match []api.StackSummary
	for _, s := range stacks {
		if equalFold(s.Name, ref) {
			match = append(match, s)
		}
	}
	if len(match) == 1 {
		return match[0].Id, nil
	}
	if len(match) > 1 {
		return uuid.UUID{}, fmt.Errorf("several stacks are named %q; give its id (see `gitgrit stack list`)", ref)
	}
	if len(stacks) == 0 {
		return uuid.UUID{}, errors.New("no stacks yet")
	}
	names := make([]string, len(stacks))
	for i, s := range stacks {
		names[i] = s.Name
	}
	return uuid.UUID{}, fmt.Errorf("no stack %q; stacks: %s", ref, strings.Join(names, ", "))
}
