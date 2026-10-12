package cmd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"strings"

	"github.com/spf13/cobra"

	"github.com/kfirzvi-com/gitgrit/cli/internal/output"
)

func newAPICmd() *cobra.Command {
	var method, input string
	var fields []string
	cmd := &cobra.Command{
		Use:   "api <path>",
		Short: "Call any API endpoint, authenticated",
		Long: `Make an authenticated request to the GitGrit API and print the response.

<path> is relative to /api/v1/ unless it starts with "/". {workspace} is
replaced with the selected workspace's id. -f key=value adds query
parameters to a GET, and JSON body fields otherwise (values that parse as
JSON are sent as JSON: -f draft=true, -f 'events=["push"]').

  gitgrit api me/
  gitgrit api workspaces/{workspace}/projects/
  gitgrit api -X POST workspaces/{workspace}/standards/test/ --input body.json

The full reference is the OpenAPI document at /api/v1/schema/ (docs at /api/v1/docs/).`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			s, err := open()
			if err != nil {
				return err
			}
			path := args[0]
			if strings.Contains(path, "{workspace}") {
				ws, err := s.Workspace(cmd.Context(), workspaceFlag)
				if err != nil {
					return err
				}
				path = strings.ReplaceAll(path, "{workspace}", ws.ID.String())
			}
			if !strings.HasPrefix(path, "/") {
				path = "/api/v1/" + path
			}
			method = strings.ToUpper(method)
			if method == "" {
				method = http.MethodGet
				if len(fields) > 0 || input != "" {
					method = http.MethodPost
				}
			}
			var body io.Reader
			query := url.Values{}
			switch {
			case input != "":
				data, err := os.ReadFile(input)
				if err != nil {
					return err
				}
				body = bytes.NewReader(data)
			case len(fields) > 0 && method == http.MethodGet:
				for _, f := range fields {
					k, v, _ := strings.Cut(f, "=")
					query.Add(k, v)
				}
			case len(fields) > 0:
				obj := map[string]any{}
				for _, f := range fields {
					k, v, _ := strings.Cut(f, "=")
					var parsed any
					if json.Unmarshal([]byte(v), &parsed) == nil {
						obj[k] = parsed
					} else {
						obj[k] = v
					}
				}
				data, _ := json.Marshal(obj)
				body = bytes.NewReader(data)
			}
			u := s.Host + path
			if len(query) > 0 {
				u += "?" + query.Encode()
			}
			req, err := http.NewRequestWithContext(cmd.Context(), method, u, body)
			if err != nil {
				return err
			}
			tok, err := s.Token(cmd.Context())
			if err != nil {
				return err
			}
			req.Header.Set("Authorization", "Bearer "+tok)
			req.Header.Set("Accept", "application/json")
			if body != nil {
				req.Header.Set("Content-Type", "application/json")
			}
			resp, err := s.HTTP.Do(req)
			if err != nil {
				return err
			}
			defer resp.Body.Close()
			data, err := io.ReadAll(resp.Body)
			if err != nil {
				return err
			}
			if len(data) > 0 {
				if err := output.JSON(cmd.OutOrStdout(), data); err != nil {
					return err
				}
			}
			if resp.StatusCode >= 400 {
				fmt.Fprintf(cmd.ErrOrStderr(), "HTTP %d\n", resp.StatusCode)
				return &ExitError{Code: 1}
			}
			return nil
		},
	}
	cmd.Flags().StringVarP(&method, "method", "X", "", "HTTP method (default GET, or POST with fields)")
	cmd.Flags().StringArrayVarP(&fields, "field", "f", nil, "key=value parameter (repeatable)")
	cmd.Flags().StringVar(&input, "input", "", "file with the JSON request body")
	return cmd
}
