// Package version holds the build's version, stamped at link time:
//
//	go build -ldflags "-X github.com/kfirzvi-com/gitgrit/cli/internal/version.Version=v1.2.3 \
//	                   -X github.com/kfirzvi-com/gitgrit/cli/internal/version.Channel=stable"
package version

var (
	// Version is the release tag (v1.2.3), an edge build (v1.2.4-edge.<sha>)
	// or a local build (v1.2.3-dev+<sha>, or "dev" without git).
	Version = "dev"
	// Channel is "stable", "edge" or "dev". It picks what `gitgrit update`
	// moves to by default.
	Channel = "dev"
)

// UserAgent identifies the CLI to the server.
func UserAgent() string { return "gitgrit-cli/" + Version }

// IsDev reports whether this is a local build, which never nags about updates.
func IsDev() bool { return Channel == "dev" }
