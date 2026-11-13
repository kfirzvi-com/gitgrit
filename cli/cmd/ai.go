package cmd

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strconv"
	"strings"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newAICmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "ai",
		Short: "AI usage and budgets",
		Long: "Tokens spent per provider and model, and the budgets that keep them in check.\n\n" +
			"Budgets are an allow-list: a model runs only once it has a budget.",
	}
	c.AddCommand(aiUsage(), aiModels(), newBudgetCmd())
	return c
}

func aiUsage() *cobra.Command {
	var period string
	cmd := &cobra.Command{
		Use:   "usage",
		Short: "Tokens spent this day, week or month, per provider and model",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			p := api.GetAiUsageParamsPeriod(period)
			resp, err := t.s.API.GetAiUsageWithResponse(cmd.Context(), t.ws.ID, &api.GetAiUsageParams{Period: &p})
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() { printUsage(cmd.OutOrStdout(), resp.JSON200) })
		},
	}
	cmd.Flags().StringVar(&period, "period", "month", "day, week or month (the current one)")
	return cmd
}

func printUsage(w io.Writer, u *api.AIUsage) {
	b := u.Budgets
	fmt.Fprintf(w, "Since %s · budgets: %d ok, %d low, %d used up", u.Starts.Format("Jan 2"), b.Ok, b.Near, b.UsedUp)
	if b.Stopping > 0 {
		fmt.Fprintf(w, " (%d stopping runs)", b.Stopping)
	}
	fmt.Fprintln(w)
	if len(u.Providers) == 0 {
		fmt.Fprintln(w, "\nNo AI providers yet.")
		return
	}
	fmt.Fprintln(w)
	tb := output.NewTable(w, "PROVIDER", "MODEL", "INPUT", "OUTPUT", "CALLS", "BUDGET")
	for _, p := range u.Providers {
		for _, m := range p.Models {
			tb.Row(p.Name, m.Model, tokens(m.InputTokens), tokens(m.OutputTokens), fmt.Sprint(m.Calls), budgetState(m))
		}
	}
	tb.Flush()

	fmt.Fprintln(w)
	tb = output.NewTable(w, "SPENT ON", "INPUT", "OUTPUT", "CALLS")
	for _, c := range u.Categories {
		tb.Row(c.Label, tokens(c.InputTokens), tokens(c.OutputTokens), fmt.Sprint(c.Calls))
	}
	tb.Flush()

	if len(u.Standards) == 0 {
		return
	}
	fmt.Fprintln(w)
	tb = output.NewTable(w, "STANDARD", "SHARE", "INPUT", "OUTPUT", "RUNS", "")
	for _, s := range u.Standards {
		heavy := ""
		if s.Heavy {
			heavy = fmt.Sprintf("heavy: %.1f× the median", s.TimesMedian)
		}
		tb.Row(s.Name, fmt.Sprintf("%.0f%%", s.Share*100), tokens(s.InputTokens), tokens(s.OutputTokens), fmt.Sprint(s.Runs), heavy)
	}
	tb.Flush()
}

// budgetState says, per model, whether it may run and how its budgets stand.
func budgetState(m api.ModelUsage) string {
	if m.Blocked {
		return "none: blocked"
	}
	parts := make([]string, len(m.Budgets))
	for i, b := range m.Budgets {
		parts[i] = fmt.Sprintf("%s %s", b.Period, levelWord(b))
	}
	return strings.Join(parts, ", ")
}

func levelWord(b api.Budget) string {
	switch b.Level {
	case "reached":
		if b.StopsRuns {
			return "used up, stopping runs"
		}
		return "used up"
	case "near":
		return "low"
	}
	return "ok"
}

func aiModels() *cobra.Command {
	return &cobra.Command{
		Use:   "models",
		Short: "Models a budget can cover, and which are blocked for having none",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListAiModelsWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				if len(*resp.JSON200) == 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "No AI providers yet.")
					return
				}
				tb := output.NewTable(cmd.OutOrStdout(), "PROVIDER", "MODEL", "ROLES", "BUDGET")
				for _, m := range *resp.JSON200 {
					state := "yes"
					if m.Blocked {
						state = "none: blocked"
					}
					tb.Row(m.Provider.Name, m.Model, dash(strings.Join(m.Roles, ", ")), state)
				}
				tb.Flush()
			})
		},
	}
}

func newBudgetCmd() *cobra.Command {
	c := &cobra.Command{
		Use:     "budget",
		Aliases: []string{"budgets"},
		Short:   "AI budgets per model (owners and admins change them)",
	}
	c.AddCommand(budgetList(), budgetSet(), budgetRemove())
	return c
}

func budgetList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "Budgets, with what each current period has used",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListAiBudgetsWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				if len(*resp.JSON200) == 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "No budgets: no model can run. Set one with `gitgrit ai budget set <model>`.")
					return
				}
				tb := output.NewTable(cmd.OutOrStdout(), "PROVIDER", "MODEL", "PERIOD", "INPUT", "OUTPUT", "LOW AT", "AT LIMIT", "STATE", "RESETS")
				for _, b := range *resp.JSON200 {
					low := "—"
					if b.LowAtPercent != nil {
						low = fmt.Sprintf("%d%% left", *b.LowAtPercent)
					}
					atLimit := "warn"
					if b.StopAtLimit {
						atLimit = "stop runs"
					}
					tb.Row(b.Provider.Name, b.Model, string(b.Period),
						usedOf(b.Used.InputTokens, b.InputLimit), usedOf(b.Used.OutputTokens, b.OutputLimit),
						low, atLimit, levelWord(b), b.Window.Resets.Local().Format("Jan 2 15:04"))
				}
				tb.Flush()
			})
		},
	}
}

func budgetSet() *cobra.Command {
	var provider, period, input, output string
	var lowAt int
	var stop bool
	cmd := &cobra.Command{
		Use:   "set <model>",
		Short: "Set or change a model's budget for a period (owners and admins)",
		Long: "One budget per provider, model and period: setting one that exists changes it,\n" +
			"only in the flags you pass. Limits take 500k, 2M or 1,000,000; \"none\" clears one.\n" +
			"A budget needs at least one limit.",
		Example: "  gitgrit ai budget set claude-haiku-4-5 --per month --input 20M --output 2M --low-at 20\n" +
			"  gitgrit ai budget set claude-haiku-4-5 --per month --stop-at-limit\n" +
			"  gitgrit ai budget set gpt-5 --provider OpenAI --per day --output none",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			f := cmd.Flags()
			fields := map[string]any{}
			for name, value := range map[string]string{"input_limit": input, "output_limit": output} {
				flag := strings.TrimSuffix(name, "_limit")
				if !f.Changed(flag) {
					continue
				}
				n, err := parseTokens(value)
				if err != nil {
					return fmt.Errorf("--%s: %w", flag, err)
				}
				fields[name] = n
			}
			if f.Changed("low-at") {
				if lowAt == 0 {
					fields["low_at_percent"] = nil
				} else {
					fields["low_at_percent"] = lowAt
				}
			}
			if f.Changed("stop-at-limit") {
				fields["stop_at_limit"] = stop
			}

			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			model, err := modelFor(cmd, t, args[0], provider)
			if err != nil {
				return err
			}
			existing, err := budgetFor(cmd, t, model, period)
			if err != nil {
				return err
			}
			var status int
			var body []byte
			if existing != nil {
				resp, err := t.s.API.UpdateAiBudgetWithBodyWithResponse(cmd.Context(), t.ws.ID, existing.Id, "application/json", jsonBody(fields))
				if err != nil {
					return err
				}
				if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
					return err
				}
				status, body = resp.StatusCode(), resp.Body
			} else {
				fields["provider_id"], fields["model"], fields["period"] = model.Provider.Id, model.Model, period
				resp, err := t.s.API.CreateAiBudgetWithBodyWithResponse(cmd.Context(), t.ws.ID, "application/json", jsonBody(fields))
				if err != nil {
					return err
				}
				if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
					return err
				}
				status, body = resp.StatusCode(), resp.Body
			}
			return emit(cmd.OutOrStdout(), body, func() {
				verb := "Changed"
				if status == 201 {
					verb = "Set"
				}
				fmt.Fprintf(cmd.OutOrStdout(), "%s the %s budget of %s %s.\n", verb, period, model.Provider.Name, model.Model)
			})
		},
	}
	f := cmd.Flags()
	f.StringVar(&provider, "provider", "", "provider name or id (needed when several offer the model)")
	f.StringVar(&period, "per", "month", "day, week or month")
	f.StringVar(&input, "input", "", "input-token limit per period, or none")
	f.StringVar(&output, "output", "", "output-token limit per period, or none")
	f.IntVar(&lowAt, "low-at", 0, "warn owners and admins when this % is left (0: only when used up)")
	f.BoolVar(&stop, "stop-at-limit", false, "hold back new runs on the model once used up (--stop-at-limit=false to only warn)")
	return cmd
}

func budgetRemove() *cobra.Command {
	var provider, period string
	cmd := &cobra.Command{
		Use:     "remove <model>",
		Aliases: []string{"rm"},
		Short:   "Remove a model's budget (owners and admins); with none left, the model stops running",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			model, err := modelFor(cmd, t, args[0], provider)
			if err != nil {
				return err
			}
			b, err := budgetFor(cmd, t, model, period)
			if err != nil {
				return err
			}
			if b == nil {
				return fmt.Errorf("%s has no %s budget; see `gitgrit ai budget list`", model.Model, period)
			}
			resp, err := t.s.API.DeleteAiBudgetWithResponse(cmd.Context(), t.ws.ID, b.Id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Removed the %s budget of %s %s.\n", period, model.Provider.Name, model.Model)
			return nil
		},
	}
	cmd.Flags().StringVar(&provider, "provider", "", "provider name or id (needed when several offer the model)")
	cmd.Flags().StringVar(&period, "per", "month", "day, week or month")
	return cmd
}

// modelFor finds the provider and model a budget is for.
func modelFor(cmd *cobra.Command, t *target, model, provider string) (api.BudgetableModel, error) {
	resp, err := t.s.API.ListAiModelsWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return api.BudgetableModel{}, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return api.BudgetableModel{}, err
	}
	return pickModel(*resp.JSON200, model, provider)
}

func pickModel(models []api.BudgetableModel, model, provider string) (api.BudgetableModel, error) {
	pid, pidErr := uuid.Parse(provider)
	var found []api.BudgetableModel
	for _, m := range models {
		if m.Model != model {
			continue
		}
		if provider != "" && !equalFold(m.Provider.Name, provider) && (pidErr != nil || m.Provider.Id != pid) {
			continue
		}
		found = append(found, m)
	}
	switch len(found) {
	case 1:
		return found[0], nil
	case 0:
		return api.BudgetableModel{}, fmt.Errorf("no model %q; see `gitgrit ai models`", model)
	}
	names := make([]string, len(found))
	for i, m := range found {
		names[i] = m.Provider.Name
	}
	return api.BudgetableModel{}, fmt.Errorf("%s is offered by %s; pass --provider", model, strings.Join(names, ", "))
}

// budgetFor finds the model's budget for the period; nil when it has none.
func budgetFor(cmd *cobra.Command, t *target, m api.BudgetableModel, period string) (*api.Budget, error) {
	resp, err := t.s.API.ListAiBudgetsWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return nil, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return nil, err
	}
	for _, b := range *resp.JSON200 {
		if b.Provider.Id == m.Provider.Id && b.Model == m.Model && string(b.Period) == period {
			return &b, nil
		}
	}
	return nil, nil
}

func jsonBody(fields map[string]any) io.Reader {
	data, _ := json.Marshal(fields)
	return bytes.NewReader(data)
}

// parseTokens reads a limit: 500k, 2M, 1.5M, 1,000,000; "none" is no limit (nil).
func parseTokens(s string) (*int, error) {
	text := strings.ToLower(strings.NewReplacer(",", "", "_", "", " ", "").Replace(s))
	if text == "none" || text == "" {
		return nil, nil
	}
	mult := 1.0
	switch {
	case strings.HasSuffix(text, "k"):
		mult, text = 1e3, strings.TrimSuffix(text, "k")
	case strings.HasSuffix(text, "m"):
		mult, text = 1e6, strings.TrimSuffix(text, "m")
	case strings.HasSuffix(text, "b"):
		mult, text = 1e9, strings.TrimSuffix(text, "b")
	}
	f, err := strconv.ParseFloat(text, 64)
	if err != nil || f <= 0 {
		return nil, errors.New(`a number of tokens, like 500k, 2M or 1,000,000 (or "none")`)
	}
	n := int(f*mult + 0.5)
	return &n, nil
}

// tokens is a short token count: 950, 12.4k, 3.2M.
func tokens(n int) string {
	switch {
	case n >= 1e6:
		return strings.TrimSuffix(fmt.Sprintf("%.1f", float64(n)/1e6), ".0") + "M"
	case n >= 1e3:
		return strings.TrimSuffix(fmt.Sprintf("%.1f", float64(n)/1e3), ".0") + "k"
	}
	return fmt.Sprint(n)
}

// usedOf is "1.2M / 5M", or the used count alone when there is no limit.
func usedOf(used int, limit *int) string {
	if limit == nil {
		return tokens(used) + " (no limit)"
	}
	return tokens(used) + " / " + tokens(*limit)
}
