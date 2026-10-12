package update

import (
	"archive/tar"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"testing"
)

func tarball(t *testing.T, files map[string]string) []byte {
	t.Helper()
	var buf bytes.Buffer
	gz := gzip.NewWriter(&buf)
	tw := tar.NewWriter(gz)
	for name, body := range files {
		tw.WriteHeader(&tar.Header{Name: name, Mode: 0o755, Size: int64(len(body)), Typeflag: tar.TypeReg})
		tw.Write([]byte(body))
	}
	tw.Close()
	gz.Close()
	return buf.Bytes()
}

func TestInstallReplacesTheBinaryOnlyWhenTheChecksumMatches(t *testing.T) {
	archive := tarball(t, map[string]string{"gitgrit": "NEW", "README.md": "x"})
	sum := sha256.Sum256(archive)
	good := hex.EncodeToString(sum[:]) + "  gitgrit_linux_amd64.tar.gz\n"
	sums := good
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		switch r.URL.Path {
		case "/a.tar.gz":
			w.Write(archive)
		case "/checksums.txt":
			w.Write([]byte(sums))
		default:
			http.NotFound(w, r)
		}
	}))
	defer srv.Close()
	rel := &Release{TagName: "v9.9.9", Assets: []Asset{
		{Name: "gitgrit_linux_amd64.tar.gz", URL: srv.URL + "/a.tar.gz"},
		{Name: "checksums.txt", URL: srv.URL + "/checksums.txt"},
	}}
	exe := filepath.Join(t.TempDir(), "gitgrit")
	os.WriteFile(exe, []byte("OLD"), 0o755)

	sums = "0000  gitgrit_linux_amd64.tar.gz\n"
	if err := installTo(context.Background(), http.DefaultClient, rel, exe, "linux", "amd64"); err == nil {
		t.Fatal("installed despite a checksum mismatch")
	}
	if b, _ := os.ReadFile(exe); string(b) != "OLD" {
		t.Fatalf("binary changed after a failed install: %q", b)
	}

	sums = good
	if err := installTo(context.Background(), http.DefaultClient, rel, exe, "linux", "amd64"); err != nil {
		t.Fatal(err)
	}
	b, _ := os.ReadFile(exe)
	info, _ := os.Stat(exe)
	if string(b) != "NEW" || info.Mode().Perm() != 0o755 {
		t.Errorf("binary = %q, mode %v; want NEW, 0755", b, info.Mode().Perm())
	}
	if err := installTo(context.Background(), http.DefaultClient, rel, exe, "darwin", "arm64"); err == nil {
		t.Error("installed without an asset for the platform")
	}
}

func TestNewer(t *testing.T) {
	cases := []struct {
		cur, latest, channel string
		want                 bool
	}{
		{"v1.2.3", "v1.2.4", "stable", true},
		{"v1.2.3", "v1.3.0", "stable", true},
		{"v1.2.3", "v2.0.0", "stable", true},
		{"v1.2.3", "v1.2.3", "stable", false},
		{"v1.2.4", "v1.2.3", "stable", false},
		{"v1.10.0", "v1.9.9", "stable", false},
		{"v1.2.3-dev+abc", "v1.2.3", "stable", true},
		{"v1.2.4-edge.abc", "v1.2.3", "stable", false},
		{"v1.2.4-edge.abc", "v1.2.4-edge.def", "edge", true},
		{"v1.2.4-edge.abc", "v1.2.4-edge.abc", "edge", false},
		{"dev", "v1.0.0", "stable", false},
		{"v1.0.0", "", "stable", false},
	}
	for _, c := range cases {
		if got := Newer(c.cur, c.latest, c.channel); got != c.want {
			t.Errorf("Newer(%q, %q, %q) = %v; want %v", c.cur, c.latest, c.channel, got, c.want)
		}
	}
}

func TestChecksumAndExtract(t *testing.T) {
	sums := []byte("abc123  gitgrit_linux_amd64.tar.gz\ndef456  gitgrit_darwin_arm64.tar.gz\n")
	if got, ok := Checksum(sums, "gitgrit_darwin_arm64.tar.gz"); !ok || got != "def456" {
		t.Errorf("Checksum = %q, %v", got, ok)
	}
	if _, ok := Checksum(sums, "gitgrit_windows_amd64.zip"); ok {
		t.Error("found a checksum that isn't there")
	}

	bin, err := extract(tarball(t, map[string]string{"README.md": "readme", "gitgrit": "BINARY"}), "linux")
	if err != nil || string(bin) != "BINARY" {
		t.Errorf("extract = %q, %v", bin, err)
	}
}

func TestAssetNameAndEdgeVersion(t *testing.T) {
	if AssetName("darwin", "arm64") != "gitgrit_darwin_arm64.tar.gz" || AssetName("windows", "amd64") != "gitgrit_windows_amd64.zip" {
		t.Error("unexpected asset names")
	}
	edge := Release{TagName: "edge", Name: "v1.2.4-edge.abc1234"}
	stable := Release{TagName: "v1.2.3", Name: "v1.2.3"}
	if edge.Version() != "v1.2.4-edge.abc1234" || stable.Version() != "v1.2.3" {
		t.Error("unexpected release versions")
	}
}
