package cmd

import (
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

func TestParseTokens(t *testing.T) {
	cases := map[string]int{"500k": 500_000, "2M": 2_000_000, "1.5m": 1_500_000, "1,000,000": 1_000_000, "42": 42}
	for in, want := range cases {
		got, err := parseTokens(in)
		if err != nil || got == nil || *got != want {
			t.Errorf("parseTokens(%q) = %v, %v; want %d", in, got, err, want)
		}
	}
	if got, err := parseTokens("none"); err != nil || got != nil {
		t.Errorf(`"none" should clear the limit; got %v, %v`, got, err)
	}
	for _, bad := range []string{"lots", "-5", "0"} {
		if _, err := parseTokens(bad); err == nil {
			t.Errorf("parseTokens(%q) should fail", bad)
		}
	}
}

func TestTokens(t *testing.T) {
	for n, want := range map[int]string{950: "950", 12_400: "12.4k", 3_000_000: "3M", 1_260_000: "1.3M"} {
		if got := tokens(n); got != want {
			t.Errorf("tokens(%d) = %q; want %q", n, got, want)
		}
	}
}

func TestPickModel(t *testing.T) {
	anthropic := api.ProviderRef{Id: uuid.New(), Name: "Anthropic"}
	bedrock := api.ProviderRef{Id: uuid.New(), Name: "Bedrock"}
	models := []api.BudgetableModel{
		{Provider: anthropic, Model: "haiku"},
		{Provider: bedrock, Model: "haiku"},
		{Provider: anthropic, Model: "sonnet"},
	}

	if m, err := pickModel(models, "sonnet", ""); err != nil || m.Provider.Name != "Anthropic" {
		t.Errorf("one provider offers sonnet: got %v, %v", m, err)
	}
	if _, err := pickModel(models, "haiku", ""); err == nil || !strings.Contains(err.Error(), "--provider") {
		t.Errorf("two providers offer haiku: want a --provider hint, got %v", err)
	}
	if m, err := pickModel(models, "haiku", "bedrock"); err != nil || m.Provider.Id != bedrock.Id {
		t.Errorf("by provider name: got %v, %v", m, err)
	}
	if m, err := pickModel(models, "haiku", anthropic.Id.String()); err != nil || m.Provider.Id != anthropic.Id {
		t.Errorf("by provider id: got %v, %v", m, err)
	}
	if _, err := pickModel(models, "opus", ""); err == nil {
		t.Error("an unknown model should fail")
	}
}

func TestBudgetState(t *testing.T) {
	if got := budgetState(api.ModelUsage{Blocked: true}); got != "none: blocked" {
		t.Errorf("blocked: %q", got)
	}
	m := api.ModelUsage{Budgets: []api.Budget{
		{Period: "day", Level: "reached", StopsRuns: true},
		{Period: "month", Level: "near"},
	}}
	if got := budgetState(m); got != "day used up, stopping runs, month low" {
		t.Errorf("got %q", got)
	}
}

func TestFindStack(t *testing.T) {
	id := uuid.New()
	stacks := []api.StackSummary{{Id: id, Name: "Payments"}, {Id: uuid.New(), Name: "Web"}}
	if got, err := findStack(stacks, "payments"); err != nil || got != id {
		t.Errorf("by name, any case: got %v, %v", got, err)
	}
	if _, err := findStack(stacks, "Data"); err == nil || !strings.Contains(err.Error(), "Payments, Web") {
		t.Errorf("unknown stack should list the stacks: %v", err)
	}
}

func TestLitLights(t *testing.T) {
	lights := []api.WarningLight{
		{Title: "Required standard failed", Count: 2, Lit: true},
		{Title: "Grade below A", Count: 0},
		{Title: "AI budget low", Count: 1, Lit: true},
	}
	if got := litLights(lights); got != "Required standard failed (2), AI budget low (1)" {
		t.Errorf("got %q", got)
	}
}
