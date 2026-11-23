package cmd

import (
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

func TestFindProjects(t *testing.T) {
	apiP := api.Project{Id: uuid.New(), Name: "api", FullPath: "acme/api"}
	mono := api.Project{Id: uuid.New(), Name: "mono", FullPath: "acme/mono"}
	orders := api.Project{Id: uuid.New(), Name: "orders", FullPath: "acme/mono", RootPath: "services/orders"}
	web := api.Project{Id: uuid.New(), Name: "web", FullPath: "acme/mono", RootPath: "apps/web"}
	webToo := api.Project{Id: uuid.New(), Name: "web", FullPath: "acme/mono", RootPath: "legacy/web"}
	all := []api.Project{apiP, mono, orders, web, webToo}

	cases := map[string]api.Project{
		"acme/api":                    apiP,
		"ACME/mono":                   mono,
		"api":                         apiP,
		"acme/mono#services/orders":   orders,
		"acme/mono:services/orders":   orders,
		"acme/mono#/services/orders/": orders,
		"orders":                      orders,
		orders.Id.String():            orders,
	}
	for ref, want := range cases {
		got, err := findProjects(all, []string{ref})
		if err != nil || len(got) != 1 || got[0].Id != want.Id {
			t.Errorf("%q: got %v, %v; want %s", ref, got, err, projectRef(want))
		}
	}
	if _, err := findProjects(all, []string{"web"}); err == nil || !strings.Contains(err.Error(), "acme/mono#apps/web") {
		t.Errorf("two projects are named web: want both offered, got %v", err)
	}
	if _, err := findProjects(all, []string{"acme/api", "nope"}); err == nil || !strings.Contains(err.Error(), `"nope"`) {
		t.Errorf("an unknown ref should fail by name: %v", err)
	}
}

func TestProjectRef(t *testing.T) {
	if got := projectRef(api.Project{Name: "mono", FullPath: "acme/mono"}); got != "acme/mono" {
		t.Errorf("whole repository: %q", got)
	}
	if got := projectRef(api.Project{Name: "orders", FullPath: "acme/mono", RootPath: "services/orders"}); got != "acme/mono#services/orders" {
		t.Errorf("inside a monorepo: %q", got)
	}
	if got := projectRef(api.Project{Name: "Release builds"}); got != "Release builds" {
		t.Errorf("artifact project: %q", got)
	}
}

func TestFindStackRefusesAnAmbiguousName(t *testing.T) {
	stacks := []api.StackSummary{{Id: uuid.New(), Name: "Web"}, {Id: uuid.New(), Name: "web"}}
	if _, err := findStack(stacks, "web"); err == nil || !strings.Contains(err.Error(), "its id") {
		t.Errorf("want an ask for the id, got %v", err)
	}
}
