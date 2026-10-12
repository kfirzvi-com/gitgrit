// Package update finds and installs new CLI releases from GitHub.
//
// Two channels, both GitHub releases of kfirzvi-com/gitgrit:
//   - stable: the latest vX.Y.Z release (GitHub's /releases/latest never
//     returns a prerelease), cut by the same tag that deploys production;
//   - edge: one prerelease tagged "edge", rebuilt on every push to main
//     (what staging runs). Its name is the build's version.
//
// Every release carries gitgrit_<os>_<arch>.tar.gz (.zip on Windows) and
// checksums.txt; downloads are verified against it before installing.
package update

import (
	"archive/tar"
	"archive/zip"
	"bufio"
	"bytes"
	"compress/gzip"
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
)

// Repo hosts the releases.
const Repo = "kfirzvi-com/gitgrit"

// APIBase is GitHub's API; tests point it at a fake.
var APIBase = "https://api.github.com"

// Asset is a downloadable release file.
type Asset struct {
	Name string `json:"name"`
	URL  string `json:"browser_download_url"`
}

// Release is a GitHub release.
type Release struct {
	TagName    string  `json:"tag_name"`
	Name       string  `json:"name"`
	Prerelease bool    `json:"prerelease"`
	Assets     []Asset `json:"assets"`
}

// Version is the CLI version the release contains: the tag for stable
// releases, the release name for the rolling edge release.
func (r *Release) Version() string {
	if r.TagName == "edge" {
		return r.Name
	}
	return r.TagName
}

// Latest fetches the newest release on a channel ("stable" or "edge").
func Latest(ctx context.Context, hc *http.Client, channel string) (*Release, error) {
	path := "/releases/latest"
	switch channel {
	case "stable", "":
	case "edge":
		path = "/releases/tags/edge"
	default:
		return nil, fmt.Errorf("unknown channel %q (stable or edge)", channel)
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, APIBase+"/repos/"+Repo+path, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/vnd.github+json")
	resp, err := hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, fmt.Errorf("no %s release published yet", channel)
	}
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("checking for releases: HTTP %d", resp.StatusCode)
	}
	var r Release
	if err := json.NewDecoder(resp.Body).Decode(&r); err != nil {
		return nil, err
	}
	return &r, nil
}

type semver struct {
	major, minor, patch int
	pre                 string
}

func parse(v string) (semver, bool) {
	v = strings.TrimPrefix(v, "v")
	if i := strings.IndexByte(v, '+'); i >= 0 {
		v = v[:i]
	}
	var s semver
	core := v
	if i := strings.IndexByte(v, '-'); i >= 0 {
		core, s.pre = v[:i], v[i+1:]
	}
	parts := strings.Split(core, ".")
	if len(parts) != 3 {
		return s, false
	}
	nums := []*int{&s.major, &s.minor, &s.patch}
	for i, p := range parts {
		n, err := strconv.Atoi(p)
		if err != nil {
			return s, false
		}
		*nums[i] = n
	}
	return s, true
}

// Newer reports whether latest should replace current. On the edge channel
// any different build is "newer" (edge builds of one version differ only by
// commit); on stable it's a semver comparison where a release outranks its
// own prereleases.
func Newer(current, latest, channel string) bool {
	if latest == "" || latest == current {
		return false
	}
	if channel == "edge" {
		return true
	}
	c, ok1 := parse(current)
	l, ok2 := parse(latest)
	if !ok1 || !ok2 {
		return false
	}
	for _, d := range [][2]int{{l.major, c.major}, {l.minor, c.minor}, {l.patch, c.patch}} {
		if d[0] != d[1] {
			return d[0] > d[1]
		}
	}
	return c.pre != "" && l.pre == "" // v1.2.3 beats v1.2.3-dev
}

// AssetName is this platform's archive name.
func AssetName(goos, goarch string) string {
	ext := "tar.gz"
	if goos == "windows" {
		ext = "zip"
	}
	return fmt.Sprintf("gitgrit_%s_%s.%s", goos, goarch, ext)
}

func download(ctx context.Context, hc *http.Client, url string) ([]byte, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := hc.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("downloading %s: HTTP %d", url, resp.StatusCode)
	}
	return io.ReadAll(io.LimitReader(resp.Body, 200<<20))
}

// Checksum finds an asset's SHA-256 in a checksums.txt ("<hex>  <name>").
func Checksum(sums []byte, name string) (string, bool) {
	sc := bufio.NewScanner(bytes.NewReader(sums))
	for sc.Scan() {
		f := strings.Fields(sc.Text())
		if len(f) == 2 && strings.TrimPrefix(f[1], "*") == name {
			return f[0], true
		}
	}
	return "", false
}

// Install downloads this platform's binary from the release, verifies it,
// and replaces the running executable.
func Install(ctx context.Context, hc *http.Client, r *Release) error {
	exe, err := os.Executable()
	if err != nil {
		return err
	}
	if exe, err = filepath.EvalSymlinks(exe); err != nil {
		return err
	}
	return installTo(ctx, hc, r, exe, runtime.GOOS, runtime.GOARCH)
}

func installTo(ctx context.Context, hc *http.Client, r *Release, exe, goos, goarch string) error {
	name := AssetName(goos, goarch)
	var archiveURL, sumsURL string
	for _, a := range r.Assets {
		switch a.Name {
		case name:
			archiveURL = a.URL
		case "checksums.txt":
			sumsURL = a.URL
		}
	}
	if archiveURL == "" || sumsURL == "" {
		return fmt.Errorf("release %s has no %s (or checksums.txt)", r.Version(), name)
	}
	sums, err := download(ctx, hc, sumsURL)
	if err != nil {
		return err
	}
	want, ok := Checksum(sums, name)
	if !ok {
		return fmt.Errorf("checksums.txt does not list %s", name)
	}
	archive, err := download(ctx, hc, archiveURL)
	if err != nil {
		return err
	}
	got := sha256.Sum256(archive)
	if hex.EncodeToString(got[:]) != want {
		return errors.New("checksum mismatch: refusing to install the download")
	}
	bin, err := extract(archive, goos)
	if err != nil {
		return err
	}
	return replace(exe, bin)
}

func binaryName(goos string) string {
	if goos == "windows" {
		return "gitgrit.exe"
	}
	return "gitgrit"
}

func extract(archive []byte, goos string) ([]byte, error) {
	want := binaryName(goos)
	if goos == "windows" {
		zr, err := zip.NewReader(bytes.NewReader(archive), int64(len(archive)))
		if err != nil {
			return nil, err
		}
		for _, f := range zr.File {
			if filepath.Base(f.Name) == want {
				rc, err := f.Open()
				if err != nil {
					return nil, err
				}
				defer rc.Close()
				return io.ReadAll(rc)
			}
		}
		return nil, fmt.Errorf("%s not found in the archive", want)
	}
	gz, err := gzip.NewReader(bytes.NewReader(archive))
	if err != nil {
		return nil, err
	}
	tr := tar.NewReader(gz)
	for {
		h, err := tr.Next()
		if err == io.EOF {
			return nil, fmt.Errorf("%s not found in the archive", want)
		}
		if err != nil {
			return nil, err
		}
		if h.Typeflag == tar.TypeReg && filepath.Base(h.Name) == want {
			return io.ReadAll(tr)
		}
	}
}

// replace swaps the binary at path for bin. The new file is written next to
// it and renamed over it, so a failure never leaves a half-written binary.
// Windows can't overwrite a running .exe, so the old one is moved aside.
func replace(path string, bin []byte) error {
	dir := filepath.Dir(path)
	tmp, err := os.CreateTemp(dir, ".gitgrit-new-*")
	if err != nil {
		return fmt.Errorf("can't write to %s (try again with sudo?): %w", dir, err)
	}
	defer os.Remove(tmp.Name())
	if _, err := tmp.Write(bin); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Chmod(0o755); err != nil {
		tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if runtime.GOOS == "windows" {
		old := path + ".old"
		os.Remove(old)
		if err := os.Rename(path, old); err != nil {
			return err
		}
	}
	return os.Rename(tmp.Name(), path)
}
