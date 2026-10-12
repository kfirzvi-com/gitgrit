// Package gitctx reads the git repository the CLI runs in, so commands can
// default to "this repo" and "this branch".
package gitctx

import (
	"net/url"
	"os/exec"
	"strings"
)

func git(args ...string) string {
	out, err := exec.Command("git", args...).Output()
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(out))
}

// OriginURL is `git remote get-url origin`, or "" outside a repo.
func OriginURL() string { return git("remote", "get-url", "origin") }

// CurrentBranch is the checked-out branch, or "" when detached or outside a repo.
func CurrentBranch() string {
	b := git("rev-parse", "--abbrev-ref", "HEAD")
	if b == "HEAD" {
		return ""
	}
	return b
}

// FullPath turns a remote URL into "org/repo" (GitLab subgroups kept):
// git@github.com:acme/api.git, https://github.com/acme/api and
// ssh://git@gitlab.example.com:2222/group/sub/api.git all work.
func FullPath(remote string) string {
	remote = strings.TrimSpace(remote)
	var path string
	if u, err := url.Parse(remote); err == nil && u.Scheme != "" && u.Host != "" {
		path = u.Path
	} else if i := strings.Index(remote, ":"); i >= 0 && !strings.Contains(remote[:i], "/") {
		path = remote[i+1:] // scp-like: git@host:org/repo.git
	} else {
		return ""
	}
	path = strings.Trim(strings.TrimSuffix(strings.TrimSuffix(path, "/"), ".git"), "/")
	return path
}

// SafeRemote drops credentials embedded in a remote URL
// (https://user:token@host/...) so they are never sent anywhere.
func SafeRemote(remote string) string {
	u, err := url.Parse(remote)
	if err != nil || u.Scheme == "" || u.User == nil {
		return remote
	}
	if u.Scheme == "ssh" {
		u.User = url.User(u.User.Username()) // ssh://git@host: the user is not a secret
	} else {
		u.User = nil
	}
	return u.String()
}

// FullSHA expands an abbreviated commit SHA using the local repository; it
// returns the input unchanged when it can't (outside a repo, unknown commit).
func FullSHA(sha string) string {
	if len(sha) >= 40 {
		return sha
	}
	if full := git("rev-parse", "--verify", "--quiet", sha+"^{commit}"); len(full) == 40 {
		return full
	}
	return sha
}
