package cmd

import (
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

func TestFindComponents(t *testing.T) {
	api1 := api.ComponentProject{Id: uuid.New(), Name: "api", FullPath: "acme/api"}
	mono := api.ComponentProject{Id: uuid.New(), Name: "mono", FullPath: "acme/mono"}
	apiRoot := api.Component{Id: uuid.New(), Name: "api", Project: api1}
	monoRoot := api.Component{Id: uuid.New(), Name: "mono", Project: mono}
	orders := api.Component{Id: uuid.New(), Name: "orders", Path: "services/orders", Project: mono}
	web := api.Component{Id: uuid.New(), Name: "web", Path: "apps/web", Project: mono}
	webToo := api.Component{Id: uuid.New(), Name: "web", Path: "legacy/web", Project: mono}
	all := []api.Component{apiRoot, monoRoot, orders, web, webToo}

	cases := map[string]api.Component{
		"acme/api":                  apiRoot,
		"ACME/mono":                 monoRoot,
		"api":                       apiRoot,
		"acme/mono:services/orders": orders,
		"mono:/services/orders/":    orders,
		"orders":                    orders,
		orders.Id.String():          orders,
		api1.Id.String() + ":":      apiRoot,
	}
	for ref, want := range cases {
		got, err := findComponents(all, []string{ref})
		if err != nil || len(got) != 1 || got[0].Id != want.Id {
			t.Errorf("%q: got %v, %v; want %s", ref, got, err, componentLabel(want))
		}
	}
	if _, err := findComponents(all, []string{"web"}); err == nil || !strings.Contains(err.Error(), "acme/mono:apps/web") {
		t.Errorf("two components are named web: want both offered, got %v", err)
	}
	if _, err := findComponents(all, []string{"acme/api", "nope"}); err == nil || !strings.Contains(err.Error(), `"nope"`) {
		t.Errorf("an unknown ref should fail by name: %v", err)
	}
}

func TestComponentLabel(t *testing.T) {
	p := api.ComponentProject{Name: "mono", FullPath: "acme/mono"}
	if got := componentLabel(api.Component{Project: p}); got != "acme/mono" {
		t.Errorf("root: %q", got)
	}
	if got := componentLabel(api.Component{Project: p, Path: "services/orders"}); got != "acme/mono:services/orders" {
		t.Errorf("service: %q", got)
	}
	if got := componentLabel(api.Component{Project: api.ComponentProject{Name: "Release builds"}}); got != "Release builds" {
		t.Errorf("artifact project: %q", got)
	}
}

func TestFindStackRefusesAnAmbiguousName(t *testing.T) {
	stacks := []api.StackSummary{{Id: uuid.New(), Name: "Web"}, {Id: uuid.New(), Name: "web"}}
	if _, err := findStack(stacks, "web"); err == nil || !strings.Contains(err.Error(), "its id") {
		t.Errorf("want an ask for the id, got %v", err)
	}
}
