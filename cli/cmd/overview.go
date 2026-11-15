package cmd

import (
	"fmt"
	"io"
	"strings"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newOverviewCmd() *cobra.Command {
	return &cobra.Command{
		Use:     "overview",
		Aliases: []string{"dashboard"},
		Short:   "The workspace at a glance: health, warning lights, what needs you",
		Long: "What the dashboard's cockpit shows: projects counted by health (never one grade\n" +
			"for many), the warning lights that are on, and the projects that need you.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetOverviewWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() { printOverview(cmd.OutOrStdout(), resp.JSON200) })
		},
	}
}

func printOverview(w io.Writer, o *api.Overview) {
	h := o.Health
	fmt.Fprintf(w, "%d projects: %d failed · %d need attention · %d healthy\n", h.Total, h.Failed, h.NeedsAttention, h.Healthy)
	fmt.Fprintf(w, "Checks: %d this week, %d last week\n", o.Checks.ThisWeek, o.Checks.LastWeek)
	if o.LastCheck != nil {
		fmt.Fprintf(w, "Last check: %s, %s on %s\n", output.Ago(o.LastCheck.At), o.LastCheck.Project.Name, o.LastCheck.Branch)
	}
	if lit := litLights(o.Lights); lit != "" {
		fmt.Fprintf(w, "Warning lights: %s\n", lit)
	} else {
		fmt.Fprintln(w, "Warning lights: all off")
	}
	if len(o.NeedsYou) == 0 {
		fmt.Fprintln(w, "\nNothing needs you.")
		return
	}
	fmt.Fprintln(w)
	tb := output.NewTable(w, "PROJECT", "HEALTH", "GRADE", "WHY", "OWNER", "STACKS")
	for _, r := range o.NeedsYou {
		tb.Row(r.Project.Name, tone(r.Tone), grade(r.Grade), dash(r.Why), dash(r.Owner), dash(strings.Join(r.Stacks, ", ")))
	}
	tb.Flush()
}

// litLights names the lamps that are on: "Required standard failed (2), No score (1)".
func litLights(lights []api.WarningLight) string {
	var on []string
	for _, l := range lights {
		if l.Lit {
			on = append(on, fmt.Sprintf("%s (%d)", l.Title, l.Count))
		}
	}
	return strings.Join(on, ", ")
}

func tone(t api.LevelEnum) string {
	switch t {
	case "failed":
		return "✗ failed"
	case "needs_attention":
		return "! needs attention"
	case "healthy":
		return "✓ healthy"
	}
	return "—"
}

func grade(d *api.ScoreDisplay) string {
	if d == nil {
		return "—"
	}
	return d.Text
}

func dash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}
