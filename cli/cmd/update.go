package cmd

import (
	"fmt"
	"net/http"
	"time"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/update"
	"github.com/kfirzvi-com/gitgrit/cli/internal/version"
)

func newUpdateCmd() *cobra.Command {
	var channel string
	var checkOnly bool
	cmd := &cobra.Command{
		Use:   "update",
		Short: "Update gitgrit to the newest release",
		Long: `Download the newest gitgrit for this machine from GitHub releases, verify its
checksum and replace this binary.

Channels: stable (default; the latest release) and edge (a prerelease built
from main). An edge build stays on edge unless you pass --channel.
Installed with Homebrew? Use ` + "`brew upgrade gitgrit`" + ` instead.`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if channel == "" {
				channel = "stable"
				if version.Channel == "edge" {
					channel = "edge"
				}
			}
			hc := &http.Client{Timeout: 5 * time.Minute}
			rel, err := update.Latest(cmd.Context(), hc, channel)
			if err != nil {
				return err
			}
			latest, out := rel.Version(), cmd.OutOrStdout()
			sameChannel := channel == version.Channel
			if sameChannel && !update.Newer(version.Version, latest, channel) {
				fmt.Fprintf(out, "gitgrit %s is the newest %s release.\n", version.Version, channel)
				return nil
			}
			if checkOnly {
				fmt.Fprintf(out, "gitgrit %s is available (you have %s).\n", latest, version.Version)
				return nil
			}
			fmt.Fprintf(out, "Updating gitgrit %s → %s…\n", version.Version, latest)
			if err := update.Install(cmd.Context(), hc, rel); err != nil {
				return err
			}
			fmt.Fprintf(out, "Updated to %s.\n", latest)
			return nil
		},
	}
	cmd.Flags().StringVar(&channel, "channel", "", "stable or edge (default: this build's channel)")
	cmd.Flags().BoolVar(&checkOnly, "check", false, "only report whether an update exists")
	return cmd
}
