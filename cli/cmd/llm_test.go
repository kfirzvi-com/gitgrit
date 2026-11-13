package cmd

import (
	"reflect"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

func TestProviderOfModel(t *testing.T) {
	anthropic := api.LLMProvider{Id: uuid.New(), DisplayName: "Anthropic", Models: []string{"haiku", "sonnet"}}
	proxy := api.LLMProvider{Id: uuid.New(), DisplayName: "Proxy", Models: []string{"haiku", "qwen"}}
	all := []api.LLMProvider{anthropic, proxy}

	if p, err := providerOfModel(all, "sonnet", ""); err != nil || p.Id != anthropic.Id {
		t.Errorf("only Anthropic offers sonnet: got %v, %v", p.DisplayName, err)
	}
	if _, err := providerOfModel(all, "haiku", ""); err == nil || !strings.Contains(err.Error(), "--provider") {
		t.Errorf("two offer haiku: want a --provider hint, got %v", err)
	}
	if p, err := providerOfModel(all, "haiku", "proxy"); err != nil || p.Id != proxy.Id {
		t.Errorf("--provider by name: got %v, %v", p.DisplayName, err)
	}
	if p, err := providerOfModel(all, "custom-model", anthropic.Id.String()); err != nil || p.Id != anthropic.Id {
		t.Errorf("--provider by id, a model not in its list: got %v, %v", p.DisplayName, err)
	}
	if _, err := providerOfModel(all, "opus", ""); err == nil {
		t.Error("nobody offers opus: want an error")
	}
}

func TestSplitList(t *testing.T) {
	if got := splitList(" a, b,,c "); !reflect.DeepEqual(got, []string{"a", "b", "c"}) {
		t.Errorf("got %v", got)
	}
}
