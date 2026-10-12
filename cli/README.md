# gitgrit — the GitGrit CLI

Work with GitGrit from your terminal, scripts, CI and AI agents: project health,
commit checks, standards, and any API call.

## Install

```sh
curl -fsSL https://gitgrit.dev/install.sh | sh                        # latest stable
curl -fsSL https://gitgrit.dev/install.sh | GITGRIT_VERSION=v0.9.0 sh  # a specific release
curl -fsSL https://gitgrit.dev/install.sh | GITGRIT_CHANNEL=edge sh    # built from main (prerelease)
```

One static binary, no runtime, installed as `gitgrit` with `ggr` as a short
name (a symlink; skipped if you already have a different `ggr`). `gitgrit update` moves to the newest release on
your channel; at most once a day the CLI mentions when one is out
(`GITGRIT_NO_UPDATE_NOTIFIER=1`, or `CI`, turns that off).

## Use

```sh
gitgrit auth login                      # browser sign-in to app.gitgrit.dev (or: ggr auth login)
gitgrit workspace use "Acme"            # if you're in several
cd ~/src/acme/api                       # project commands default to this repo
gitgrit health                          # project health; --branch for a branch's
gitgrit commits --branch feature/x      # commits with their checks
gitgrit check --wait                    # check the branch's latest commit; exit 1 on failures
gitgrit standard list
gitgrit api workspaces/{workspace}/projects/   # anything else in /api/v1
```

Every command takes `--json` for the raw API response.

### Other instances (self-hosted, local dev)

```sh
gitgrit auth login --host gitgrit.example.com
gitgrit auth login --host localhost:8000
gitgrit health --host localhost:8000    # or GITGRIT_HOST=localhost:8000
gitgrit auth status                     # every instance you're logged in to
gitgrit auth switch --host localhost:8000   # change the default
```

Each instance keeps its own login and default workspace in
`~/.config/gitgrit/hosts.yml` (mode 0600). The last one you logged in to is the
default. Plain `http://` is only allowed for local hosts.

### CI

Create a workspace token (workspace settings → API Tokens) and:

```yaml
- run: curl -fsSL https://gitgrit.dev/install.sh | sh
- run: ~/.local/bin/gitgrit check --branch "$GITHUB_REF_NAME" --sha "$GITHUB_SHA" --wait
  env:
    GITGRIT_TOKEN: ${{ secrets.GITGRIT_TOKEN }}
```

`--fail-under 80` fails on the score instead of on any failing standard.

## Develop

```sh
make -C cli                  # builds bin/gitgrit (version vX.Y.Z-dev+<sha>)
./bin/gitgrit --host localhost:8000 auth login
make -C cli test
```

The API client in `internal/api/` is generated from `openapi.yaml`, the
server's OpenAPI document. After changing the API:

```sh
make -C cli spec             # re-export openapi.yaml from Django and regenerate
```

CI fails when either is stale, so the CLI can't drift from the server.

### Releases

The CLI shares the server's version. A `vX.Y.Z` tag builds it with goreleaser and
attaches it to that release (channel *stable*). Every push to `main` that touches
`cli/` rebuilds the `edge` prerelease (channel *edge*, version
`vX.Y.Z-edge.<sha>`).
