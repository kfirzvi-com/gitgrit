package cmd

import (
	"io"
	"mime"
	"mime/multipart"
	"os"
	"path/filepath"
	"testing"
)

func TestCommitFormCarriesTheArchiveAndFields(t *testing.T) {
	path := filepath.Join(t.TempDir(), "dist.zip")
	if err := os.WriteFile(path, []byte("PK-archive"), 0o600); err != nil {
		t.Fatal(err)
	}
	contentType, body, err := commitForm(path, "Release 1.4.2", "")
	if err != nil {
		t.Fatal(err)
	}
	_, params, err := mime.ParseMediaType(contentType)
	if err != nil {
		t.Fatal(err)
	}
	form, err := multipart.NewReader(body, params["boundary"]).ReadForm(1 << 20)
	if err != nil {
		t.Fatal(err)
	}
	if got := form.Value["message"]; len(got) != 1 || got[0] != "Release 1.4.2" {
		t.Errorf("message = %v", got)
	}
	if _, ok := form.Value["branch"]; ok {
		t.Error("an empty branch should not be sent (the server picks the default)")
	}
	files := form.File["archive"]
	if len(files) != 1 || files[0].Filename != "dist.zip" {
		t.Fatalf("archive = %v", files)
	}
	f, _ := files[0].Open()
	data, _ := io.ReadAll(f)
	if string(data) != "PK-archive" {
		t.Errorf("archive bytes = %q", data)
	}
}

func TestCommitFormNeedsTheFile(t *testing.T) {
	if _, _, err := commitForm(filepath.Join(t.TempDir(), "missing.zip"), "", ""); err == nil {
		t.Error("expected an error for a missing archive")
	}
}
