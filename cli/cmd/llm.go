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

func newLLMCmd() *cobra.Command {
	c := &cobra.Command{
		Use:   "llm",
		Short: "LLM providers and roles",
		Long: "The LLM providers (API keys) GitGrit may use, and its roles: which provider and\n" +
			"model does which kind of work. A role's model runs only once it has an AI budget\n" +
			"(`gitgrit ai budget set`).",
	}
	provider := &cobra.Command{
		Use:     "provider",
		Aliases: []string{"providers"},
		Short:   "LLM providers and the models each key can use (owners and admins change them)",
	}
	provider.AddCommand(llmProviderList(), llmProviderAdd(), llmProviderEdit(), llmProviderRemove(),
		llmProviderTest(), llmProviderRefresh())
	role := &cobra.Command{
		Use:     "role",
		Aliases: []string{"roles"},
		Short:   "Which provider and model does which work (owners and admins set them)",
	}
	role.AddCommand(llmRoleList(), llmRoleSet(), llmRoleClear())
	c.AddCommand(provider, role)
	return c
}

func llmProviders(cmd *cobra.Command, t *target) ([]api.LLMProvider, error) {
	resp, err := t.s.API.ListLlmProvidersWithResponse(cmd.Context(), t.ws.ID)
	if err != nil {
		return nil, err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return nil, err
	}
	return *resp.JSON200, nil
}

func llmProviderList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "The workspace's LLM providers",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListLlmProvidersWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				if len(*resp.JSON200) == 0 {
					fmt.Fprintln(cmd.OutOrStdout(), "No LLM providers yet. Add one: gitgrit llm provider add --type anthropic --key-stdin")
					return
				}
				tb := output.NewTable(cmd.OutOrStdout(), "NAME", "TYPE", "MODELS", "ROLES", "ENDPOINT", "ID")
				for _, p := range *resp.JSON200 {
					tb.Row(p.DisplayName, string(p.ProviderType), fmt.Sprint(len(p.Models)), dash(roleNames(p.Roles)), dash(p.BaseUrl), p.Id.String())
				}
				tb.Flush()
			})
		},
	}
}

// readKey takes an API key from stdin, the flag, or the environment.
func readKey(cmd *cobra.Command, fromStdin bool, flag string) (string, error) {
	if fromStdin {
		line, err := bufio.NewReader(cmd.InOrStdin()).ReadString('\n')
		if err != nil && line == "" {
			return "", fmt.Errorf("reading the key from stdin: %w", err)
		}
		return strings.TrimSpace(line), nil
	}
	if flag != "" {
		return flag, nil
	}
	return os.Getenv("GITGRIT_LLM_API_KEY"), nil
}

func llmProviderAdd() *cobra.Command {
	var kind, key, name, baseURL string
	var keyStdin bool
	cmd := &cobra.Command{
		Use:   "add",
		Short: "Add an LLM provider (owners and admins); finds the models the key can use",
		Example: "  gitgrit llm provider add --type anthropic --key-stdin < key.txt\n" +
			"  gitgrit llm provider add --type litellm_proxy --base-url https://llm.example.com --key-stdin",
		Args: cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			apiKey, err := readKey(cmd, keyStdin, key)
			if err != nil {
				return err
			}
			if apiKey == "" {
				return errors.New("pass the key with --key-stdin (or --key, or $GITGRIT_LLM_API_KEY)")
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			body := api.LLMProviderCreateRequest{ProviderType: api.LLMProviderTypeEnum(kind), ApiKey: apiKey, DisplayName: &name, BaseUrl: &baseURL}
			resp, err := t.s.API.CreateLlmProviderWithResponse(cmd.Context(), t.ws.ID, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				w, p := cmd.OutOrStdout(), resp.JSON201
				if len(p.Models) > 0 {
					fmt.Fprintf(w, "Added %s: %d models this key can use.\n", p.DisplayName, len(p.Models))
					fmt.Fprintln(w, "Next: give a model a budget (gitgrit ai budget set <model>) and a role (gitgrit llm role set).")
					return
				}
				fmt.Fprintf(w, "Added %s, but no model this key can use was found.", p.DisplayName)
				if p.Note != "" {
					fmt.Fprintf(w, " The provider said: %s.", p.Note)
				}
				fmt.Fprintf(w, "\nName them by hand: gitgrit llm provider edit %q --models <model>,…\n", p.DisplayName)
			})
		},
	}
	f := cmd.Flags()
	f.StringVar(&kind, "type", "", "anthropic, openai, azure, bedrock, vertex_ai, gemini, mistral, ollama or litellm_proxy")
	f.StringVar(&key, "key", "", "the API key (prefer --key-stdin: flags end up in shell history)")
	f.BoolVar(&keyStdin, "key-stdin", false, "read the API key from stdin")
	f.StringVar(&name, "name", "", `display name (default: the type, e.g. "Anthropic")`)
	f.StringVar(&baseURL, "base-url", "", "a proxy or self-hosted endpoint")
	cmd.MarkFlagsMutuallyExclusive("key", "key-stdin")
	_ = cmd.MarkFlagRequired("type")
	return cmd
}

func llmProviderEdit() *cobra.Command {
	var name, baseURL, key, models string
	var keyStdin bool
	cmd := &cobra.Command{
		Use:   "edit <provider>",
		Short: "Change a provider's name, endpoint, key or models (owners and admins)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			f := cmd.Flags()
			body := api.PatchedLLMProviderUpdateRequest{}
			if f.Changed("name") {
				body.DisplayName = &name
			}
			if f.Changed("base-url") {
				body.BaseUrl = &baseURL
			}
			if f.Changed("models") {
				list := splitList(models)
				body.Models = &list
			}
			if keyStdin || f.Changed("key") {
				apiKey, err := readKey(cmd, keyStdin, key)
				if err != nil {
					return err
				}
				body.ApiKey = &apiKey
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			p, err := providerFor(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.UpdateLlmProviderWithResponse(cmd.Context(), t.ws.ID, p.Id, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				fmt.Fprintf(cmd.OutOrStdout(), "Updated %s.\n", resp.JSON200.DisplayName)
			})
		},
	}
	f := cmd.Flags()
	f.StringVar(&name, "name", "", "display name")
	f.StringVar(&baseURL, "base-url", "", `endpoint ("" for the provider's own)`)
	f.StringVar(&key, "key", "", "a new API key (prefer --key-stdin)")
	f.BoolVar(&keyStdin, "key-stdin", false, "read a new API key from stdin")
	f.StringVar(&models, "models", "", "replace the models by hand, comma separated")
	cmd.MarkFlagsMutuallyExclusive("key", "key-stdin")
	return cmd
}

func llmProviderRemove() *cobra.Command {
	var yes bool
	cmd := &cobra.Command{
		Use:     "remove <provider>",
		Aliases: []string{"rm"},
		Short:   "Remove a provider and clear the roles that use it (owners and admins)",
		Args:    cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			if !yes {
				return errors.New("removing a provider deletes its key and clears the roles that use it; pass --yes to confirm")
			}
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			p, err := providerFor(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.DeleteLlmProviderWithResponse(cmd.Context(), t.ws.ID, p.Id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Removed %s.\n", p.DisplayName)
			return nil
		},
	}
	cmd.Flags().BoolVarP(&yes, "yes", "y", false, "confirm the removal")
	return cmd
}

func llmProviderTest() *cobra.Command {
	return &cobra.Command{
		Use:   "test <provider>",
		Short: "Check that the provider accepts the key",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			p, err := providerFor(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.TestLlmProviderWithResponse(cmd.Context(), t.ws.ID, p.Id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			if err := emit(cmd.OutOrStdout(), resp.Body, func() {
				if resp.JSON200.Ok {
					fmt.Fprintf(cmd.OutOrStdout(), "✓ %s accepts the key.\n", p.DisplayName)
				} else {
					fmt.Fprintf(cmd.OutOrStdout(), "✗ %s refused the key, or couldn't be reached.\n", p.DisplayName)
				}
			}); err != nil {
				return err
			}
			if !resp.JSON200.Ok {
				return &ExitError{Code: 1}
			}
			return nil
		},
	}
}

func llmProviderRefresh() *cobra.Command {
	return &cobra.Command{
		Use:   "refresh <provider>",
		Short: "Find the models the key can use again (owners and admins)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			p, err := providerFor(cmd, t, args[0])
			if err != nil {
				return err
			}
			resp, err := t.s.API.RefreshLlmModelsWithResponse(cmd.Context(), t.ws.ID, p.Id)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				w, r := cmd.OutOrStdout(), resp.JSON200
				if len(r.Models) == 0 {
					fmt.Fprintf(w, "No model this key can use was found; kept the list as it was.")
					if r.Note != "" {
						fmt.Fprintf(w, " The provider said: %s.", r.Note)
					}
					fmt.Fprintln(w)
					return
				}
				fmt.Fprintf(w, "%s: %d models this key can use:\n  %s\n", p.DisplayName, len(r.Models), strings.Join(r.Models, "\n  "))
			})
		},
	}
}

func llmRoleList() *cobra.Command {
	return &cobra.Command{
		Use:   "list",
		Short: "Each role's provider and model",
		Args:  cobra.NoArgs,
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ListLlmRolesWithResponse(cmd.Context(), t.ws.ID)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				tb := output.NewTable(cmd.OutOrStdout(), "ROLE", "PROVIDER", "MODEL", "BUDGET")
				for _, r := range *resp.JSON200 {
					provider, model, budget := "—", "—", "—"
					if r.Provider != nil {
						provider, budget = r.Provider.Name, "none: blocked"
						if r.HasBudget {
							budget = "yes"
						}
					}
					if r.Model != nil {
						model = *r.Model
					}
					tb.Row(string(r.Role), provider, model, budget)
				}
				tb.Flush()
			})
		},
	}
}

func llmRoleSet() *cobra.Command {
	var provider string
	cmd := &cobra.Command{
		Use:     "set <role> <model>",
		Short:   "Point a role at a model (owners and admins)",
		Example: "  gitgrit llm role set reasoning claude-haiku-4-5\n  gitgrit llm role set code gpt-5 --provider OpenAI",
		Args:    cobra.ExactArgs(2),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			all, err := llmProviders(cmd, t)
			if err != nil {
				return err
			}
			p, err := providerOfModel(all, args[1], provider)
			if err != nil {
				return err
			}
			body := api.LLMRoleSetRequest{ProviderId: p.Id, Model: args[1]}
			resp, err := t.s.API.SetLlmRoleWithResponse(cmd.Context(), t.ws.ID, api.SetLlmRoleParamsRole(args[0]), body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			return emit(cmd.OutOrStdout(), resp.Body, func() {
				w, r := cmd.OutOrStdout(), resp.JSON200
				fmt.Fprintf(w, "%s now uses %s %s.\n", r.Label, p.DisplayName, args[1])
				if !r.HasBudget {
					fmt.Fprintf(w, "It has no AI budget, so it won't run yet: gitgrit ai budget set %s --provider %q --input …\n", args[1], p.DisplayName)
				}
			})
		},
	}
	cmd.Flags().StringVar(&provider, "provider", "", "provider name or id (default: the one whose key can use the model)")
	return cmd
}

func llmRoleClear() *cobra.Command {
	return &cobra.Command{
		Use:   "clear <role>",
		Short: "Clear a role (owners and admins)",
		Args:  cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			t, err := resolve(cmd.Context(), "", false)
			if err != nil {
				return err
			}
			resp, err := t.s.API.ClearLlmRoleWithResponse(cmd.Context(), t.ws.ID, api.ClearLlmRoleParamsRole(args[0]))
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			fmt.Fprintf(cmd.OutOrStdout(), "Cleared the %s role.\n", args[0])
			return nil
		},
	}
}

// providerFor finds a provider by id or name.
func providerFor(cmd *cobra.Command, t *target, ref string) (api.LLMProvider, error) {
	all, err := llmProviders(cmd, t)
	if err != nil {
		return api.LLMProvider{}, err
	}
	return findProvider(all, ref)
}

func findProvider(all []api.LLMProvider, ref string) (api.LLMProvider, error) {
	id, idErr := uuid.Parse(ref)
	for _, p := range all {
		if (idErr == nil && p.Id == id) || equalFold(p.DisplayName, ref) {
			return p, nil
		}
	}
	return api.LLMProvider{}, fmt.Errorf("no LLM provider %q; see `gitgrit llm provider list`", ref)
}

// providerOfModel picks the provider a role's model comes from: --provider,
// else the only one whose key can use the model.
func providerOfModel(all []api.LLMProvider, model, ref string) (api.LLMProvider, error) {
	if ref != "" {
		return findProvider(all, ref)
	}
	var found []api.LLMProvider
	for _, p := range all {
		for _, m := range p.Models {
			if m == model {
				found = append(found, p)
				break
			}
		}
	}
	switch len(found) {
	case 1:
		return found[0], nil
	case 0:
		return api.LLMProvider{}, fmt.Errorf("no provider's key can use %q; pass --provider, or see `gitgrit llm provider list`", model)
	}
	names := make([]string, len(found))
	for i, p := range found {
		names[i] = p.DisplayName
	}
	return api.LLMProvider{}, fmt.Errorf("%s is offered by %s; pass --provider", model, strings.Join(names, ", "))
}

func roleNames(roles []api.LLMRoleEnum) string {
	names := make([]string, len(roles))
	for i, r := range roles {
		names[i] = string(r)
	}
	return strings.Join(names, ", ")
}

func splitList(s string) []string {
	var out []string
	for _, part := range strings.Split(s, ",") {
		if part = strings.TrimSpace(part); part != "" {
			out = append(out, part)
		}
	}
	return out
}
