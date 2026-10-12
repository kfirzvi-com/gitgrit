package cmd

import (
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"time"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/auth"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func openBrowser(url string) error {
	if os.Getenv("GITGRIT_NO_BROWSER") != "" {
		return nil
	}
	switch runtime.GOOS {
	case "darwin":
		return exec.Command("open", url).Start()
	case "windows":
		return exec.Command("rundll32", "url.dll,FileProtocolHandler", url).Start()
	default:
		return exec.Command("xdg-open", url).Start()
	}
}

func newAuthCmd() *cobra.Command {
	c := &cobra.Command{Use: "auth", Short: "Log in to and out of GitGrit instances"}
	c.AddCommand(newAuthLoginCmd(), newAuthLogoutCmd(), newAuthStatusCmd(), newAuthSwitchCmd(), newAuthTokenCmd())
	return c
}

func newAuthLoginCmd() *cobra.Command {
	var noBrowser bool
	cmd := &cobra.Command{
		Use:   "login",
		Short: "Log in with your browser",
		Long: `Log in to a GitGrit instance with your browser (OAuth 2.0 with PKCE).

The instance becomes the default for later commands. Log in to several
(app.gitgrit.dev, a self-hosted one, a local dev server) and switch with --host:

  gitgrit auth login                                # app.gitgrit.dev
  gitgrit auth login --host gitgrit.example.com
  gitgrit auth login --host localhost:8000`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			ctx := cmd.Context()
			md, err := s.Metadata(ctx)
			if err != nil {
				return err
			}
			opts := auth.LoginOptions{Out: cmd.ErrOrStderr(), OpenBrowser: openBrowser}
			if noBrowser {
				opts.OpenBrowser = nil
			}
			tok, err := auth.Login(ctx, s.HTTP, md, opts)
			if err != nil {
				return err
			}
			h := s.Config.Host(s.Host)
			h.AccessToken, h.RefreshToken, h.Expiry = tok.AccessToken, tok.RefreshToken, tok.Expiry()
			s.Config.DefaultHost = s.Host
			if err := s.Config.Save(); err != nil {
				return err
			}
			me, err := s.Me(ctx)
			if err != nil {
				return err
			}
			if me.User != nil {
				h.User = me.User.Username
			}
			if len(me.Workspaces) == 1 {
				h.Workspace, h.WorkspaceName = me.Workspaces[0].Id.String(), me.Workspaces[0].Name
			}
			if err := s.Config.Save(); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Logged in to %s as %s.\n", s.Host, h.User)
			switch {
			case h.WorkspaceName != "":
				fmt.Fprintf(cmd.OutOrStdout(), "Workspace: %s\n", h.WorkspaceName)
			case len(me.Workspaces) > 1:
				fmt.Fprintln(cmd.OutOrStdout(), "You're in several workspaces; pick one with `gitgrit workspace use <name>`.")
			}
			return nil
		},
	}
	cmd.Flags().BoolVar(&noBrowser, "no-browser", false, "print the sign-in URL instead of opening a browser")
	return cmd
}

func newAuthLogoutCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "logout",
		Short: "Log out of an instance and revoke the CLI's tokens",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			h := s.HostConfig()
			if h == nil || h.AccessToken == "" {
				fmt.Fprintf(cmd.OutOrStdout(), "Not logged in to %s.\n", s.Host)
				return nil
			}
			if md, err := s.Metadata(cmd.Context()); err == nil {
				// Revoking the refresh token takes its access token with it.
				if err := auth.Revoke(cmd.Context(), s.HTTP, md, h.RefreshToken); err != nil {
					fmt.Fprintln(cmd.ErrOrStderr(), "warning:", err)
				}
				_ = auth.Revoke(cmd.Context(), s.HTTP, md, h.AccessToken)
			} else {
				fmt.Fprintln(cmd.ErrOrStderr(), "warning: couldn't reach the server to revoke the token:", err)
			}
			delete(s.Config.Hosts, s.Host)
			if s.Config.DefaultHost == s.Host {
				s.Config.DefaultHost = ""
			}
			if err := s.Config.Save(); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Logged out of %s.\n", s.Host)
			return nil
		},
	}
}

func newAuthStatusCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "status",
		Short: "Show who you are on each instance",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			out := cmd.OutOrStdout()
			if s.UsingEnvToken() {
				me, err := s.Me(cmd.Context())
				if err != nil {
					return err
				}
				fmt.Fprintf(out, "%s: using GITGRIT_TOKEN (%s)\n", s.Host, me.TokenType)
				for _, w := range me.Workspaces {
					fmt.Fprintf(out, "  workspace: %s\n", w.Name)
				}
				return nil
			}
			if len(s.Config.Hosts) == 0 {
				fmt.Fprintln(out, "Not logged in anywhere. Run `gitgrit auth login`.")
				return nil
			}
			t := output.NewTable(out, "", "INSTANCE", "USER", "WORKSPACE", "SESSION")
			for host, h := range s.Config.Hosts {
				mark := ""
				if host == s.Host {
					mark = "*"
				}
				session := "refreshes automatically"
				if h.Expiry.IsZero() {
					session = "—"
				} else if h.RefreshToken == "" && time.Until(h.Expiry) < 0 {
					session = "expired: log in again"
				}
				ws := h.WorkspaceName
				if ws == "" {
					ws = "(not chosen)"
				}
				t.Row(mark, host, h.User, ws, session)
			}
			t.Flush()
			return nil
		},
	}
}

func newAuthSwitchCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "switch",
		Short: "Make another instance you're logged in to the default",
		Long: `Make another instance the default for commands without --host:

  gitgrit auth switch --host localhost:8000
  gitgrit auth switch --host app.gitgrit.dev`,
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if hostFlag == "" {
				return fmt.Errorf("which instance? pass --host (see `gitgrit auth status`)")
			}
			s, err := open()
			if err != nil {
				return err
			}
			if h := s.HostConfig(); h == nil || h.AccessToken == "" {
				return fmt.Errorf("not logged in to %s; run `gitgrit auth login --host %s`", s.Host, hostFlag)
			}
			s.Config.DefaultHost = s.Host
			if err := s.Config.Save(); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Default instance: %s\n", s.Host)
			return nil
		},
	}
}

func newAuthTokenCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "token",
		Short: "Print a valid access token, for scripts (curl -H \"Authorization: Bearer $(gitgrit auth token)\")",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			tok, err := s.Token(cmd.Context())
			if err != nil {
				return err
			}
			fmt.Fprintln(cmd.OutOrStdout(), tok)
			return nil
		},
	}
}
