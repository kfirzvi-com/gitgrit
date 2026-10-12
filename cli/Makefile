# Local builds of the gitgrit CLI. Releases are built by goreleaser in CI
# (.goreleaser.yaml); this is for working on the CLI.
#
#   make -C cli           # build ../bin/gitgrit
#   make -C cli test      # vet + tests
#   make -C cli spec      # re-export openapi.yaml from the Django app and regenerate the client

PKG     := github.com/kfirzvi-com/gitgrit/cli/internal/version
# The last release tag, marked as a dev build of this commit: v0.9.0-dev+1a2b3c4.
VERSION ?= $(shell git describe --tags --abbrev=0 --match 'v*' 2>/dev/null || echo v0.0.0)-dev+$(shell git rev-parse --short HEAD)
LDFLAGS := -s -w -X $(PKG).Version=$(VERSION) -X $(PKG).Channel=dev
BIN     ?= ../bin/gitgrit

.PHONY: build test spec generate

build:
	go build -ldflags "$(LDFLAGS)" -o $(BIN) .

test:
	go vet ./...
	go test ./...

generate:
	go generate ./...

spec:
	cd .. && uv run python manage.py spectacular --file cli/openapi.yaml --validate --fail-on-warn
	go generate ./...
