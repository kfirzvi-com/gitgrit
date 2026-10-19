package cmd

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"strings"

	"github.com/google/uuid"
	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newConnectionCmd() *cobra.Command {
	c := &cobra.Command{
		Use:     "connection",
		Aliases: []string{"connections", "conn"},
		Short:   "Connect GitHub or GitLab to the workspace",
	}
	c.AddCommand(connectionList(), connectionAdd(), connectionApp())
	return c
}

func connectionList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "List the workspace's git platform connections",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListConnectionsWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				if len(*resp.JSON200) == 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "No connections yet. Run `gitgrit connection app` (GitHub) or `gitgrit connection add`.")
					return
				}
				tb := output.NewTable(cmd.OutOrStdout(), "NAME", "PLATFORM", "AUTH", "ACCOUNT", "ID")
				for _, c := range *resp.JSON200 {
					account := ""
					if c.AccountLogin != nil {
						account = *c.AccountLogin
					}
					tb.Row(c.DisplayName, c.Platform, string(c.AuthMethod), account, c.Id.String())
				}
				tb.Flush()
			})
		},
	}
}

func connectionAdd() *cobra.Command {
	var platform, token, name, baseURL string
	var tokenStdin bool
	cmd := &cobra.Command{
		Use:   "add",
		Short: "Connect a platform with an access token (owners and admins)",
		Long: "Connect GitHub or GitLab with a personal access token.\n\n" +
			"For GitHub the GitHub App is recommended instead (no token to rotate): `gitgrit connection app`.",
		Example: "  gitgrit connection add --platform gitlab --token-stdin < token.txt\n" +
			"  gitgrit connection add --platform gitlab --base-url https://gitlab.example.com --token-stdin",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			if tokenStdin {
				line, err := bufio.NewReader(cmd.InOrStdin()).ReadString('\n')
				if err != nil && line == "" {
					return fmt.Errorf("reading the token from stdin: %w", err)
				}
				token = strings.TrimSpace(line)
			}
			if token == "" {
				token = os.Getenv("GITGRIT_CONNECTION_TOKEN")
			}
			if token == "" {
				return errors.New("pass the token with --token-stdin (or --token, or $GITGRIT_CONNECTION_TOKEN)")
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			body := api.ConnectionCreateRequest{
				Platform:    api.PlatformEnum(platform),
				AccessToken: token,
				DisplayName: &name,
				BaseUrl:     &baseURL,
			}
			resp, err := t.s.API.CreateConnectionWithResponse(cmd.Context(), t.ws.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				c := resp.JSON201
				fmt.Fprintf(cmd.OutOrStdout(), "Connected %s (%s).\nNext: gitgrit repo list\n", c.DisplayName, c.Id)
			})
		},
	}
	f := cmd.Flags()
	f.StringVar(&platform, "platform", "github", "github or gitlab")
	f.StringVar(&token, "token", "", "the access token (prefer --token-stdin: flags end up in shell history)")
	f.BoolVar(&tokenStdin, "token-stdin", false, "read the access token from stdin")
	f.StringVar(&name, "name", "", `display name (default: "GitHub"/"GitLab")`)
	f.StringVar(&baseURL, "base-url", "", "self-hosted GitLab or GitHub Enterprise URL")
	cmd.MarkFlagsMutuallyExclusive("token", "token-stdin")
	return cmd
}

func connectionApp() *cobra.Command {
	return &cobra.Command{
		Use:   "app",
		Short: "Install the GitHub App (opens the browser)",
		Long: "The GitHub App is installed on GitHub itself, so this opens the workspace's\n" +
			"connection settings in your browser. Pick the organization and repositories\n" +
			"there, then come back and run `gitgrit repo list`.",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			url := strings.TrimSuffix(t.s.Host, "/") + "/tenants/settings/#section-connections"
			w := cmd.OutOrStdout()
			fmt.Fprintf(w, "Opening %s\n", url)
			fmt.Fprintf(w, "In the browser, make sure %s is the selected workspace, then click Install GitHub App.\n", nameOr(t.ws.Name))
			return openBrowser(url)
		},
	}
}

func nameOr(name string) string {
	if name == "" {
		return "your workspace"
	}
	return name
}

// connectionFor picks the connection a command works through: --connection
// (id or display name), else the workspace's only one.
func connectionFor(cmd *cobra.Command, t *target, flag string) (api.Connection, error) {
	resp, err := t.s.API.ListConnectionsWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return api.Connection{}, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return api.Connection{}, err
	}
	all := *resp.JSON200
	if flag != "" {
		id, idErr := uuid.Parse(flag)
		for _, c := range all {
			if (idErr == nil && c.Id == id) || equalFold(c.DisplayName, flag) {
				return c, nil
			}
		}
		return api.Connection{}, fmt.Errorf("no connection %q; see `gitgrit connection list`", flag)
	}
	switch len(all) {
	case 0:
		return api.Connection{}, errors.New("no connections yet; run `gitgrit connection app` (GitHub) or `gitgrit connection add`")
	case 1:
		return all[0], nil
	}
	names := make([]string, len(all))
	for i, c := range all {
		names[i] = c.DisplayName
	}
	return api.Connection{}, fmt.Errorf("several connections (%s); pass --connection", strings.Join(names, ", "))
}

func newRepoCmd() *cobra.Command {
	var connection, query string
	list := &cobra.Command{
		Use:   "list",
		Short: "Repositories a connection can reach",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			c, err := connectionFor(cmd, t, connection)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListRepositoriesWithResponse(cmd.Context(), t.ws.ID, c.Id, &api.ListRepositoriesParams{Q: &query})
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				tb := output.NewTable(cmd.OutOrStdout(), "REPOSITORY", "DEFAULT BRANCH", "PROJECT")
				for _, r := range *resp.JSON200 {
					added, branch := "", ""
					if r.AlreadyAdded {
						added = "added"
					}
					if r.DefaultBranch != nil {
						branch = *r.DefaultBranch
					}
					tb.Row(r.FullPath, branch, added)
				}
				tb.Flush()
			})
		},
	}
	list.Flags().StringVarP(&connection, "connection", "c", "", "connection id or name (default: the only one)")
	list.Flags().StringVarP(&query, "query", "q", "", "filter by org/repo (at most 25 shown)")
	c := &cobra.Command{Use: "repo", Aliases: []string{"repos"}, Short: "Find repositories to add as projects"}
	c.AddCommand(list)
	return c
}
