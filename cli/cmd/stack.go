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
		Long: "A stack groups components: the deployable units inside repositories. A plain\n" +
			"repository has one (its root); a monorepo one per service.",
	}
	c.AddCommand(stackList(), stackView(), stackCreate(), stackEdit(), stackDelete(),
		stackAdd(), stackRemove(), newComponentsCmd(), stackRefresh())
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
		Short: "A stack's health and its components, worst first",
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
				if len(s.Components) == 0 {
					fmt.Fprintln(w, "\nNo components yet.")
					return
				}
				fmt.Fprintln(w)
				tb := output.NewTable(w, "COMPONENT", "PROJECT", "HEALTH", "GRADE", "WHY", "CHECKED")
				for _, c := range s.Components {
					checked := "—"
					if c.LastChecked != nil {
						checked = output.Ago(*c.LastChecked)
					}
					tb.Row(componentName(c), c.Project.Name, tone(c.Tone), grade(c.Grade), dash(c.Why), checked)
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
		Example: "  gitgrit stack create Payments --description \"Checkout and billing\"\n  gitgrit stack add Payments acme/checkout acme/mono:services/billing",
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
				fmt.Fprintf(cmd.OutOrStdout(), "Created %s (%s).\nNext: gitgrit stack add %q <component>…\n", resp.JSON201.Name, resp.JSON201.Id, resp.JSON201.Name)
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
		Short:   "Delete a stack (its components stay; only the grouping goes)",
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

const componentHelp = "A component is its id, a project (org/repo: its root component), org/repo:path\n" +
	"(a monorepo service), or its name. With none, this repository's root component.\n" +
	"See them all with `gitgrit stack components`."

func stackAdd() *cobra.Command {
	return &cobra.Command{
		Use:     "add <stack> [component…]",
		Short:   "Add components to a stack",
		Long:    "Add components to a stack.\n\n" + componentHelp,
		Example: "  gitgrit stack add Payments                       # this repository\n  gitgrit stack add Payments acme/checkout acme/mono:services/billing",
		Args:    cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, stack, comps, err := stackAndComponents(cmd, args)
			if err != nil {
				return err
			}
			var ids []uuid.UUID
			seen := map[uuid.UUID]bool{}
			for _, c := range comps {
				if !seen[c.Id] {
					seen[c.Id] = true
					ids = append(ids, c.Id)
				}
			}
			resp, err := t.s.API.AddStackComponentsWithResponse(cmd.Context(), t.ws.ID, stack, api.ComponentIdsRequest{ComponentIds: ids})
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				n := resp.JSON200.Added
				fmt.Fprintf(cmd.OutOrStdout(), "Added %d component%s to %s", n, plural(n), args[0])
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
		Use:   "remove <stack> [component…]",
		Short: "Take components out of a stack",
		Long:  "Take components out of a stack.\n\n" + componentHelp,
		Args:  cobra.MinimumNArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, stack, comps, err := stackAndComponents(cmd, args)
			if err != nil {
				return err
			}
			for _, c := range comps {
				resp, err := t.s.API.RemoveStackComponentWithResponse(cmd.Context(), t.ws.ID, stack, c.Id)
				if err != nil {
					return err
				}
				if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
					return fmt.Errorf("%s: %w", componentLabel(c), err)
				}
				fmt.Fprintf(cmd.OutOrStdout(), "Removed %s from %s.\n", componentLabel(c), args[0])
			}
			return nil
		},
	}
}

func newComponentsCmd() *cobra.Command {
	var project string
	cmd := &cobra.Command{
		Use:   "components",
		Short: "The workspace's components and the stacks each belongs to",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), project, project != "")
			if err != nil {
				return err
			}
			params := &api.ListComponentsParams{}
			if project != "" {
				params.ProjectId = &t.p.ID
			}
			resp, err := t.s.API.ListComponentsWithResponse(cmd.Context(), t.ws.ID, params)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				tb := output.NewTable(cmd.OutOrStdout(), "COMPONENT", "NAME", "STACKS")
				for _, c := range *resp.JSON200 {
					names := make([]string, len(c.Stacks))
					for i, s := range c.Stacks {
						names[i] = s.Name
					}
					tb.Row(componentLabel(c), c.Name, dash(strings.Join(names, ", ")))
				}
				tb.Flush()
			})
		},
	}
	cmd.Flags().StringVarP(&project, "project", "p", "", "only this project's (id or org/repo)")
	return cmd
}

// stackAndComponents resolves `<stack> [component…]`; no component means
// this repository's root one.
func stackAndComponents(cmd *cobra.Command, args []string) (*target, uuid.UUID, []api.Component, error) {
	refs := args[1:]
	t, err := resolve(cmd.Context(), "", len(refs) == 0)
	if err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	stack, err := stackID(cmd, t, args[0])
	if err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	resp, err := t.s.API.ListComponentsWithResponse(cmd.Context(), t.ws.ID, &api.ListComponentsParams{})
	if err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return nil, uuid.UUID{}, nil, err
	}
	if len(refs) == 0 {
		refs = []string{t.p.ID.String() + ":"}
	}
	comps, err := findComponents(*resp.JSON200, refs)
	return t, stack, comps, err
}

// findComponents resolves each ref: a component id; a project (id, org/repo
// or name) for its root component; project:path; or a component name.
func findComponents(all []api.Component, refs []string) ([]api.Component, error) {
	out := make([]api.Component, 0, len(refs))
	for _, ref := range refs {
		var match []api.Component
		project, path, hasPath := strings.Cut(ref, ":")
		id, idErr := uuid.Parse(ref)
		for _, c := range all {
			isProject := equalFold(c.Project.FullPath, project) || equalFold(c.Project.Name, project) || c.Project.Id.String() == project
			switch {
			case idErr == nil && c.Id == id:
				match = append(match, c)
			case isProject && strings.Trim(c.Path, "/") == strings.Trim(path, "/") && (hasPath || c.Path == ""):
				match = append(match, c)
			case !hasPath && idErr != nil && !isProject && equalFold(c.Name, ref):
				match = append(match, c)
			}
		}
		switch len(match) {
		case 0:
			return nil, fmt.Errorf("no component %q; see `gitgrit stack components`", ref)
		case 1:
			out = append(out, match[0])
		default:
			labels := make([]string, len(match))
			for i, c := range match {
				labels[i] = componentLabel(c)
			}
			return nil, fmt.Errorf("%q could be %s; name it as org/repo:path", ref, strings.Join(labels, ", "))
		}
	}
	return out, nil
}

// componentLabel is how a component is named on the command line: org/repo
// for a root component, org/repo:path for one inside a monorepo.
func componentLabel(c api.Component) string {
	project := c.Project.FullPath
	if project == "" {
		project = c.Project.Name
	}
	if c.Path == "" {
		return project
	}
	return project + ":" + c.Path
}

// componentName shows a monorepo component with its path.
func componentName(c api.StackComponent) string {
	if c.Path == "" {
		return c.Name
	}
	return c.Name + " (" + c.Path + ")"
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
