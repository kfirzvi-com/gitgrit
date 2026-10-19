package cmd

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newStandardCmd() *cobra.Command {
	c := &cobra.Command{Use: "standard", Aliases: []string{"standards"}, Short: "Manage the workspace's standards"}
	c.AddCommand(standardList(), standardView(), standardTest(), standardCreate(), standardEdit(), standardDelete(),
		standardSwitch(true), standardSwitch(false))
	return c
}

func standardID(arg string) (uuid.UUID, error) {
	id, err := uuid.Parse(arg)
	if err != nil {
		return id, fmt.Errorf("%q is not a standard id; see `gitgrit standard list`", arg)
	}
	return id, nil
}

func standardList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List standards",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListStandardsWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				tb := output.NewTable(cmd.OutOrStdout(), "NAME", "STATE", "EVENTS", "LABELS", "ID")
				for _, s := range *resp.JSON200 {
					tb.Row(s.Name, standardState(s.Enabled, s.Draft), strings.Join(s.Events, ","), strings.Join(s.Labels, ","), s.Id.String())
				}
				tb.Flush()
			})
		},
	}
}

func standardView() *cobra.Command {
	var codeOnly bool
	cmd := &cobra.Command{
		Use:   "view <id>",
		Short: "Show a standard and its code",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := standardID(args[0])
			if err != nil {
				return err
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetStandardWithResponse(cmd.Context(), t.ws.ID, id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			s, w := resp.JSON200, cmd.OutOrStdout()
			if codeOnly {
				fmt.Fprint(w, s.Code)
				return nil
			}
			return emit(w, resp.Body, func() {
				fmt.Fprintf(w, "%s\n%s\n\n%s\n", s.Name, s.Description, s.Code)
			})
		},
	}
	cmd.Flags().BoolVar(&codeOnly, "code", false, "print only the code (e.g. > standard.py)")
	return cmd
}

func standardTest() *cobra.Command {
	var mockFile string
	cmd := &cobra.Command{
		Use:   "test <file.py>",
		Short: "Dry-run standard code in the sandbox against mock data",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			code, err := os.ReadFile(args[0])
			if err != nil {
				return err
			}
			body := api.StandardTestRequest{Code: string(code)}
			if mockFile != "" {
				raw, err := os.ReadFile(mockFile)
				if err != nil {
					return err
				}
				var mock map[string]interface{}
				if err := json.Unmarshal(raw, &mock); err != nil {
					return fmt.Errorf("%s: %w", mockFile, err)
				}
				body.MockInput = &mock
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.TestStandardWithResponse(cmd.Context(), t.ws.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			r := resp.JSON200
			if err := emit(cmd.OutOrStdout(), resp.Body, func() {
				mark := "✓ passed"
				if !r.Passed {
					mark = "✗ failed"
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%s · score %d\n%s\n", mark, r.Score, r.Message)
			}); err != nil {
				return err
			}
			if !r.Passed {
				return &ExitError{Code: 1}
			}
			return nil
		},
	}
	cmd.Flags().StringVar(&mockFile, "mock", "", "JSON file with mock project data (files, languages, members, …)")
	return cmd
}

func standardCreate() *cobra.Command {
	var name, file, description string
	var events, labels, languages []string
	var draft bool
	cmd := &cobra.Command{
		Use:   "create",
		Short: "Create a standard from a Python file",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if name == "" || file == "" {
				return errors.New("--name and --file are required")
			}
			code, err := os.ReadFile(file)
			if err != nil {
				return err
			}
			evs := make([]api.EventsEnum, len(events))
			for i, e := range events {
				evs[i] = api.EventsEnum(e)
			}
			body := api.StandardCreateRequest{
				Name: name, Code: string(code), Description: &description, Draft: &draft,
				Events: &evs, Labels: &labels, Languages: &languages,
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.CreateStandardWithResponse(cmd.Context(), t.ws.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() { mutationDone(cmd, "Created", resp.JSON201) })
		},
	}
	f := cmd.Flags()
	f.StringVar(&name, "name", "", "standard name")
	f.StringVarP(&file, "file", "f", "", "Python file defining evaluate(project)")
	f.StringVar(&description, "description", "", "what it checks")
	f.StringSliceVar(&events, "event", nil, "trigger events: push, pull_request, tag (repeatable)")
	f.StringSliceVar(&labels, "label", nil, "labels (repeatable)")
	f.StringSliceVar(&languages, "language", nil, "only projects using these languages (repeatable)")
	f.BoolVar(&draft, "draft", false, "save without running it")
	return cmd
}

func standardEdit() *cobra.Command {
	var name, file, description, summary string
	var publish, disable, draft bool
	cmd := &cobra.Command{
		Use:   "edit <id>",
		Short: "Change a standard (only what you pass changes; every save is versioned)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			id, err := standardID(args[0])
			if err != nil {
				return err
			}
			body := api.PatchedStandardUpdateRequest{}
			f := cmd.Flags()
			if f.Changed("name") {
				body.Name = &name
			}
			if f.Changed("description") {
				body.Description = &description
			}
			if f.Changed("file") {
				code, err := os.ReadFile(file)
				if err != nil {
					return err
				}
				c := string(code)
				body.Code = &c
			}
			yes, no := true, false
			switch {
			case publish:
				body.Draft, body.Enabled = &no, &yes
			case draft:
				body.Draft = &yes
			case disable:
				body.Enabled = &no
			}
			if f.Changed("summary") {
				body.ChangeSummary = &summary
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.UpdateStandardWithResponse(cmd.Context(), t.ws.ID, id, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() { mutationDone(cmd, "Saved", resp.JSON200) })
		},
	}
	f := cmd.Flags()
	f.StringVar(&name, "name", "", "new name")
	f.StringVarP(&file, "file", "f", "", "replace the code with this Python file")
	f.StringVar(&description, "description", "", "new description")
	f.StringVar(&summary, "summary", "", "version note")
	f.BoolVar(&publish, "publish", false, "publish a draft (active and enabled)")
	f.BoolVar(&draft, "draft", false, "turn back into a draft (stops it running)")
	f.BoolVar(&disable, "disable", false, "disable without making it a draft")
	cmd.MarkFlagsMutuallyExclusive("publish", "draft", "disable")
	return cmd
}

func standardDelete() *cobra.Command {
	var yes bool
	cmd := &cobra.Command{
		Use:   "delete <id>",
		Short: "Delete a standard",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if !yes {
				return errors.New("deleting a standard can't be undone; pass --yes to confirm")
			}
			id, err := standardID(args[0])
			if err != nil {
				return err
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.DeleteStandardWithResponse(cmd.Context(), t.ws.ID, id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			if !jsonFlag {
				fmt.Fprintln(cmd.OutOrStdout(), "Deleted.")
			}
			return nil
		},
	}
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "confirm the deletion")
	return cmd
}

func mutationDone(cmd *cobra.Command, verb string, m *api.StandardMutation) {
	w := cmd.OutOrStdout()
	fmt.Fprintf(w, "%s %s (%s).\n", verb, m.Name, m.Id)
	if m.Runs != nil {
		fmt.Fprintln(w, m.Runs.Message)
	}
}

func standardState(enabled, draft bool) string {
	switch {
	case draft:
		return "draft"
	case !enabled:
		return "disabled"
	}
	return "active"
}

// standardIDs turns standard names or ids into ids; all picks every enabled,
// non-draft standard in the workspace.
func standardIDs(cmd *cobra.Command, t *target, refs []string, all bool) ([]uuid.UUID, error) {
	ids := []uuid.UUID{}
	if len(refs) == 0 && !all {
		return ids, nil
	}
	resp, err := t.s.API.ListStandardsWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return nil, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return nil, err
	}
	standards := *resp.JSON200
	if all {
		for _, s := range standards {
			if s.Enabled && !s.Draft {
				ids = append(ids, s.Id)
			}
		}
		if len(ids) == 0 {
			return nil, errors.New("the workspace has no enabled standards; install some: gitgrit marketplace list")
		}
		return ids, nil
	}
	for _, ref := range refs {
		if id, err := uuid.Parse(ref); err == nil {
			ids = append(ids, id)
			continue
		}
		var match []uuid.UUID
		for _, s := range standards {
			if equalFold(s.Name, ref) {
				match = append(match, s.Id)
			}
		}
		switch len(match) {
		case 0:
			return nil, fmt.Errorf("no standard named %q; see `gitgrit standard list`", ref)
		case 1:
			ids = append(ids, match[0])
		default:
			return nil, fmt.Errorf("several standards are named %q; use its id", ref)
		}
	}
	return ids, nil
}

func standardSwitch(on bool) *cobra.Command {
	use, short := "disable <standard>", "Turn a standard off"
	if on {
		use, short = "enable <standard>", "Turn a standard on; it runs on its projects right away"
	}
	return &cobra.Command{
		Use:   use,
		Short: short,
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			ids, err := standardIDs(cmd, t, args, false)
			if err != nil {
				return err
			}
			var body []byte
			var result *api.StandardEnabled
			if on {
				resp, err := t.s.API.EnableStandardWithResponse(cmd.Context(), t.ws.ID, ids[0])
				if err != nil {
					return err
				}
				if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
					return err
				}
				body, result = resp.Body, resp.JSON200
			} else {
				resp, err := t.s.API.DisableStandardWithResponse(cmd.Context(), t.ws.ID, ids[0])
				if err != nil {
					return err
				}
				if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
					return err
				}
				body, result = resp.Body, resp.JSON200
			}
			return emit(cmd.OutOrStdout(), body, func() {
				w := cmd.OutOrStdout()
				fmt.Fprintf(w, "%s is %s.\n", result.Name, standardState(result.Enabled, false))
				if result.Runs != nil {
					fmt.Fprintln(w, result.Runs.Message)
				}
			})
		},
	}
}
