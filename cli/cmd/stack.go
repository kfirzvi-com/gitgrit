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
	}
	c.AddCommand(stackList(), stackView(), stackRefresh())
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
	for _, s := range stacks {
		if equalFold(s.Name, ref) {
			return s.Id, nil
		}
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
