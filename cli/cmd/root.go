// Package cmd defines the gitgrit commands.
package cmd

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/config"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
	"github.com/kfirzvi-com/gitgrit/cli/internal/session"
	"github.com/kfirzvi-com/gitgrit/cli/internal/update"
	"github.com/kfirzvi-com/gitgrit/cli/internal/version"
)

// Global flags.
var (
	hostFlag      string
	workspaceFlag string
	jsonFlag      bool
)

// ExitError ends the program with a code and no further message (the
// command already printed what happened), e.g. failing checks in CI.
type ExitError struct{ Code int }

func (e *ExitError) Error() string { return fmt.Sprintf("exit status %d", e.Code) }

var notice = make(chan string, 1)

func newRoot() *cobra.Command {
	root := &cobra.Command{
		Use:   "gitgrit",
		Short: "GitGrit from the command line",
		Long: `Work with GitGrit from your terminal, scripts, CI and AI agents.
(Installed by install.sh as gitgrit, and as ggr for short.)

Commands act on the GitGrit instance from --host, $GITGRIT_HOST or the one you
last logged in to (default: app.gitgrit.dev), and on the workspace from
--workspace, $GITGRIT_WORKSPACE or ` + "`gitgrit workspace use`" + `. Inside a git
repository, project commands default to that repository.

In CI, set GITGRIT_TOKEN to a workspace token (workspace settings → API Tokens).`,
		SilenceUsage:  true,
		SilenceErrors: true,
		Version:       version.Version,
		PersistentPreRun: func(cmd *cobra.Command, args []string) {
			if update.NotifierDisabled(version.IsDev()) || jsonFlag || cmd.Name() == "update" {
				return
			}
			go func() {
				dir, err := config.Dir()
				if err != nil {
					return
				}
				if v := update.Notice(context.Background(), dir, version.Version, version.Channel); v != "" {
					notice <- v
				}
			}()
		},
	}
	root.SetVersionTemplate("gitgrit {{.Version}} (" + version.Channel + ")\n")
	pf := root.PersistentFlags()
	pf.StringVar(&hostFlag, "host", "", "GitGrit instance for this command, e.g. gitgrit.example.com or localhost:8000 ($GITGRIT_HOST); `gitgrit auth switch` changes the default")
	pf.StringVarP(&workspaceFlag, "workspace", "w", "", "workspace name or id ($GITGRIT_WORKSPACE)")
	pf.BoolVar(&jsonFlag, "json", false, "print the API's JSON response")

	root.AddCommand(
		newAuthCmd(), newWorkspaceCmd(), newProjectCmd(), newHealthCmd(), newBranchesCmd(),
		newCommitsCmd(), newCommitCmd(), newCheckCmd(), newStandardCmd(),
		newAPICmd(), newUpdateCmd(),
	)
	return root
}

// Execute runs the CLI and returns the process exit code.
func Execute() int {
	err := newRoot().Execute()
	select {
	case v := <-notice:
		fmt.Fprintf(os.Stderr, "\nA new gitgrit is available: %s → %s. Run `gitgrit update`.\n", version.Version, v)
	default:
	}
	if err == nil {
		return 0
	}
	var exit *ExitError
	if errors.As(err, &exit) {
		return exit.Code
	}
	fmt.Fprintln(os.Stderr, "error:", err)
	return 1
}

// open starts a session on the selected host.
func open() (*session.Session, error) { return session.Open(hostFlag) }

// emit prints JSON when --json is set, otherwise calls human.
func emit(w io.Writer, body []byte, human func()) error {
	if jsonFlag {
		return output.JSON(w, body)
	}
	human()
	return nil
}
