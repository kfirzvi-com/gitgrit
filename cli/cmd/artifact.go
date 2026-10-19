package cmd

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"mime/multipart"
	"os"
	"path/filepath"
	"time"

	"github.com/spf13/cobra"
	"github.com/spf13/pflag"

	"github.com/kfirzvi-com/gitgrit/cli/internal/api"
)

// Artifact projects: projects whose files are build artifacts uploaded as
// archives instead of a Git repository. Every command here acts on one
// project, named with --project (an artifact project has no repository the
// CLI could find it from).

// artifactFlags are project add's flags for an artifact project.
type artifactFlags struct {
	on                                   bool
	name, externalID, stack, description string
}

func (a *artifactFlags) register(f *pflag.FlagSet) {
	f.BoolVar(&a.on, "artifact", false, "create an artifact project (uploaded builds) instead of adding a repository")
	f.StringVar(&a.name, "name", "", "with --artifact: the project's name (required)")
	f.StringVar(&a.externalID, "external-id", "", "with --artifact: your own id for it, which makes add idempotent (default: the name)")
	f.StringVar(&a.stack, "stack", "", "with --artifact: stack to put it in, found by name or created")
	f.StringVar(&a.description, "description", "", "with --artifact: description")
}

func addArtifactProject(cmd *cobra.Command, a artifactFlags, standards []string, allStandards bool) error {
	if a.name == "" {
		return errors.New("an artifact project needs --name")
	}
	t, err := resolve(cmd.Context(), "", false)
	if err != nil {
		return err
	}
	if a.externalID == "" {
		a.externalID = a.name
	}
	kind := api.TypeEnumArtifact
	body := api.ProjectCreateRequest{Type: &kind, Name: &a.name, ExternalId: &a.externalID}
	if a.stack != "" {
		body.Stack = &a.stack
	}
	if a.description != "" {
		body.Description = &a.description
	}
	if len(standards) > 0 || allStandards {
		ids, err := standardIDs(cmd, t, standards, allStandards)
		if err != nil {
			return err
		}
		body.Standards = &ids
	}
	resp, err := t.s.API.CreateProjectWithResponse(cmd.Context(), t.ws.ID, body)
	if err != nil {
		return err
	}
	if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
		return err
	}
	p, verb := resp.JSON201, "Added"
	if p == nil {
		p, verb = resp.JSON200, "Found"
	}
	return emit(cmd.OutOrStdout(), resp.Body, func() {
		w := cmd.OutOrStdout()
		fmt.Fprintf(w, "%s artifact project %s (%s).\n", verb, p.Name, p.Id)
		fmt.Fprintf(w, "Upload a build: gitgrit project upload <archive> --project %q\n", p.Name)
	})
}

func newProjectUploadCmd() *cobra.Command {
	var project, message, branch string
	var wait bool
	var timeout time.Duration
	var failUnder int
	cmd := &cobra.Command{
		Use:   "upload <archive>",
		Short: "Upload a build to an artifact project as a commit, and check it",
		Long: `Upload a .zip or .tar.gz of a build as a commit of an artifact project. The
standards that run on uploads check it, as they would a pushed commit. With
--wait, wait for the check and exit by the commit's score, as check does
(see its exit codes; --fail-under also fails a score under the number):

  gitgrit project upload dist.zip --project Storefront -m "Release 1.4.2" --wait`,
		Args: cobra.ExactArgs(1),
		RunE: func(cmd *cobra.Command, args []string) error {
			ctx := cmd.Context()
			if project == "" {
				return errors.New("name the artifact project with --project <id or name>")
			}
			t, err := resolve(ctx, project, true)
			if err != nil {
				return err
			}
			contentType, body, err := commitForm(args[0], message, branch)
			if err != nil {
				return err
			}
			resp, err := t.s.API.UploadProjectCommitWithBodyWithResponse(ctx, t.ws.ID, t.p.ID, contentType, body)
			if err != nil {
				return err
			}
			if err := checkResp(resp.HTTPResponse, resp.Body); err != nil {
				return err
			}
			up := resp.JSON202
			if !wait {
				return emit(cmd.OutOrStdout(), resp.Body, func() { printUpload(cmd.OutOrStdout(), up) })
			}
			if !jsonFlag {
				printUpload(cmd.ErrOrStderr(), up)
			}
			if up.Queued == 0 {
				return nil // no standard runs on uploads to this branch
			}
			ctx, cancel := context.WithTimeout(ctx, timeout)
			defer cancel()
			commit, raw, err := waitForCommit(ctx, t, up.Commit.Sha)
			if err != nil {
				return err
			}
			if err := emit(cmd.OutOrStdout(), raw, func() {
				fmt.Fprintln(cmd.OutOrStdout())
				printCommit(cmd.OutOrStdout(), commit)
			}); err != nil {
				return err
			}
			code, why := verdict(commit, failUnder)
			if why != "" && !jsonFlag {
				fmt.Fprintln(cmd.ErrOrStderr(), why)
			}
			if code != 0 {
				return &ExitError{Code: code}
			}
			return nil
		},
	}
	f := cmd.Flags()
	f.StringVarP(&project, "project", "p", "", "artifact project id or name (required)")
	f.StringVarP(&message, "message", "m", "", "commit message")
	f.StringVarP(&branch, "branch", "b", "", "branch (default: the project's default branch)")
	f.BoolVar(&wait, "wait", false, "wait for the check; exit by the commit's score, as check does")
	f.DurationVar(&timeout, "timeout", 15*time.Minute, "how long --wait waits")
	f.IntVar(&failUnder, "fail-under", -1, "with --wait, also fail when the score is under this (0-100)")
	return cmd
}

// commitForm is the multipart body of an upload: the archive, plus the
// message and branch when given.
func commitForm(path, message, branch string) (string, io.Reader, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", nil, err
	}
	defer f.Close()
	var buf bytes.Buffer
	w := multipart.NewWriter(&buf)
	part, err := w.CreateFormFile("archive", filepath.Base(path))
	if err != nil {
		return "", nil, err
	}
	if _, err := io.Copy(part, f); err != nil {
		return "", nil, err
	}
	for field, value := range map[string]string{"message": message, "branch": branch} {
		if value != "" {
			if err := w.WriteField(field, value); err != nil {
				return "", nil, err
			}
		}
	}
	if err := w.Close(); err != nil {
		return "", nil, err
	}
	return w.FormDataContentType(), &buf, nil
}

func printUpload(w io.Writer, up *api.CommitUploadResult) {
	verb := "Uploaded"
	if !up.Created {
		verb = "Already uploaded; checking again"
	}
	fmt.Fprintf(w, "%s %s on %s (%d files). %s\n", verb, up.Commit.Sha[:7], up.Commit.Branch, up.Commit.FileCount, up.Message)
}
