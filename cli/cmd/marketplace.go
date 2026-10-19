package cmd

import (
	"fmt"
	"io"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newMarketplaceCmd() *cobra.Command {
	c := &cobra.Command{
		Use:     "marketplace",
		Aliases: []string{"market", "mp"},
		Short:   "Browse and install ready-made standards",
	}
	c.AddCommand(marketplaceList(), marketplaceView(), marketplaceInstall(), marketplaceUpdate())
	return c
}

func installState(s api.MarketplaceStandard) string {
	switch {
	case s.UpdateAvailable:
		return "update available"
	case s.InstalledStandardId != nil:
		return "installed"
	}
	return ""
}

func marketplaceList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List packs and standards, and what this workspace installed",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetMarketplaceWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				w, m := cmd.OutOrStdout(), resp.JSON200
				tb := output.NewTable(w, "PACK", "STANDARDS", "INSTALLED", "DESCRIPTION")
				for _, p := range m.Packs {
					installed := 0
					for _, s := range p.Standards {
						if s.InstalledStandardId != nil {
							installed++
						}
					}
					tb.Row(p.Slug, fmt.Sprint(len(p.Standards)), fmt.Sprintf("%d/%d", installed, len(p.Standards)), clip(p.Description, 60))
				}
				tb.Flush()
				fmt.Fprintln(w)
				printMarketplaceStandards(w, m.Standards)
				fmt.Fprintln(w, "\nInstall a pack or a standard: gitgrit marketplace install <slug>")
			})
		},
	}
}

func marketplaceView() *cobra.Command {
	return &cobra.Command{
		Use:   "view <pack>",
		Short: "Show a pack's standards",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.GetMarketplacePackWithResponse(cmd.Context(), t.ws.ID, args[0])
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				w, p := cmd.OutOrStdout(), resp.JSON200
				fmt.Fprintf(w, "%s %s\n%s\n\n", p.Icon, p.Name, p.Description)
				printMarketplaceStandards(w, p.Standards)
			})
		},
	}
}

func printMarketplaceStandards(w io.Writer, standards []api.MarketplaceStandard) {
	tb := output.NewTable(w, "STANDARD", "VERSION", "STATE", "DESCRIPTION")
	for _, s := range standards {
		tb.Row(s.Slug, fmt.Sprintf("v%d", s.Version), installState(s), clip(s.Description, 60))
	}
	tb.Flush()
}

func marketplaceInstall() *cobra.Command {
	var standard bool
	cmd := &cobra.Command{
		Use:   "install <pack-or-standard>",
		Short: "Install a pack, or one standard, into the workspace",
		Long: "Install a marketplace pack (every standard in it the workspace doesn't\n" +
			"have yet) or a single standard, by slug. Installed standards are enabled\n" +
			"but attached to no project: attach them with `gitgrit project attach`.",
		Example: "  gitgrit marketplace install repo-hygiene\n" +
			"  gitgrit marketplace install --standard license-file",
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			slug, w := args[0], cmd.OutOrStdout()
			if !standard {
				resp, err := t.s.API.InstallMarketplacePackWithResponse(cmd.Context(), t.ws.ID, slug)
				if err != nil {
					return err
				}
				// Not a pack: fall through to a single standard of that slug.
				if resp.StatusCode() != 404 {
					if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
						return err
					}
					return emit(w, resp.Body, func() {
						r := resp.JSON200
						for _, s := range r.Installed {
							fmt.Fprintf(w, "Installed %s (%s).\n", s.Name, s.Id)
						}
						for _, s := range r.Skipped {
							fmt.Fprintf(w, "Already had %s (%s).\n", s.Name, s.Id)
						}
						fmt.Fprintln(w, "Attach them to a project: gitgrit project attach --all")
					})
				}
			}
			resp, err := t.s.API.InstallMarketplaceStandardWithResponse(cmd.Context(), t.ws.ID, slug)
			if err != nil {
				return err
			}
			if resp.StatusCode() == 404 {
				return fmt.Errorf("no marketplace pack or standard %q; see `gitgrit marketplace list`", slug)
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(w, resp.Body, func() {
				s := resp.JSON200
				verb := "Installed"
				if !s.Created {
					verb = "Already had"
				}
				fmt.Fprintf(w, "%s %s (%s).\nAttach it to a project: gitgrit project attach %q\n", verb, s.Name, s.Id, s.Name)
			})
		},
	}
	cmd.Flags().BoolVar(&standard, "standard", false, "the slug is a standard, not a pack")
	return cmd
}

func marketplaceUpdate() *cobra.Command {
	return &cobra.Command{
		Use:   "update <standard>",
		Short: "Update an installed standard to the marketplace's latest version",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.UpdateMarketplaceStandardWithResponse(cmd.Context(), t.ws.ID, args[0])
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				u, w := resp.JSON200, cmd.OutOrStdout()
				fmt.Fprintf(w, "Updated %s to v%d.\n", u.Name, u.Version)
				if u.Runs != nil {
					fmt.Fprintln(w, u.Runs.Message)
				}
			})
		},
	}
}

func clip(s string, n int) string {
	r := []rune(s)
	if len(r) <= n {
		return s
	}
	return string(r[:n-1]) + "…"
}
