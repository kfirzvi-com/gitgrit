# Command Line

Everything you do in the web app on the way to a health score also works from your terminal, scripts, CI, and AI agents: the `gitgrit` CLI. It's one static binary for macOS, Linux and Windows, and it talks to the same public API the web app uses.

## Install and sign in

```sh
curl -fsSL https://gitgrit.dev/install.sh | sh
gitgrit auth login
```

`auth login` signs you in through your browser. The CLI is also installed as `ggr`, for short. On Windows, download `gitgrit_windows_amd64.zip` from the [releases page](https://github.com/kfirzvi-com/gitgrit/releases).

If you're in more than one workspace, pick the one to work in:

```sh
gitgrit workspace list
gitgrit workspace use "Acme"
```

Or pass `-w "Acme"` to any command.

## Set up from the terminal

The whole [Quick Start](quickstart.md) after step 1, without leaving the terminal.

**1. Connect GitHub or GitLab.** For GitHub, install the GitHub App. GitHub only lets you do that on github.com, so this opens your browser:

```sh
gitgrit connection app
```

On GitLab, or to use a token instead (owners and admins only):

```sh
gitgrit connection add --platform gitlab --token-stdin < token.txt
```

Check that it worked, and see which repositories the connection reaches:

```console
$ gitgrit connection list
NAME                      PLATFORM  AUTH        ACCOUNT      ID
GitHub App (kfirzvi-com)  github    github_app  kfirzvi-com  3f1c2a7e-…

$ gitgrit repo list -q gitgrit-demo-a
REPOSITORY                             DEFAULT BRANCH  PROJECT
kfirzvi-com/gitgrit-demo-auth-service  main
kfirzvi-com/gitgrit-demo-api-gateway   main
```

**2. Install standards** from the marketplace:

```console
$ gitgrit marketplace list
$ gitgrit marketplace install repo-hygiene
Installed CI Configuration Required (7b3e91c2-…).
Installed CODEOWNERS File (52a9d0e4-…).
Installed GitGrit Badge in README (e0c6f318-…).
Installed License File (c42e8b75-…).
Installed README Exists (1e5d7a90-…).
```

**3. Add your repositories.** Inside a clone, `project add` picks up the repository from its `origin` remote:

```console
$ cd ~/src/gitgrit-demo-auth-service
$ gitgrit project add
Added kfirzvi-com/gitgrit-demo-auth-service (6d0b9e41-…).
No standards attached, so nothing will run. Attach some: gitgrit project attach --project kfirzvi-com/gitgrit-demo-auth-service <standard>…
```

Then attach standards. They run right away:

```console
$ gitgrit project attach "README Exists" "License File" ".gitignore Exists"
ATTACHED STANDARD  STATE   ID
.gitignore Exists  active  9a7f0c13-…
License File       active  c42e8b75-…
README Exists      active  1e5d7a90-…
Queued 3 standards on 1 project. Results appear on the project page as they finish.
```

Or do both at once, naming the repository: `gitgrit project add kfirzvi-com/gitgrit-demo-api-gateway --all-standards`.

!!! warning "Attach at least one standard"
    Only attached standards run, and `project add` attaches none unless you pass `--standard` or `--all-standards`. Attach more later with `gitgrit project attach`.

**4. See the score:**

```console
$ gitgrit health
gitgrit-demo-auth-service · project health
Score 33 · critical · 1 passed, 2 failed, 0 errored

STATUS    SCORE  STANDARD           COMMIT   RAN       MESSAGE
✓ passed  100    README Exists      1fc38e8  just now  README found: README.md
✗ failed  0      License File       1fc38e8  just now  No LICENSE file found in repository
✗ failed  0      .gitignore Exists  1fc38e8  just now  No .gitignore file found
```

## Commands

Project commands act on the repository you're in. Pass `--project org/repo` (or `-p`) to pick another one.

| Command | What it does |
|---|---|
| **Connections** | |
| `gitgrit connection list` | Git platform connections in the workspace |
| `gitgrit connection app` | Install the GitHub App (opens the browser) |
| `gitgrit connection add --platform … --token-stdin` | Connect with an access token (owners and admins) |
| `gitgrit repo list [-q filter]` | Repositories a connection reaches, and which are already projects |
| **Projects** | |
| `gitgrit project add [org/repo]` | Add a repository as a project |
| `gitgrit project list` | Projects in the workspace |
| `gitgrit project view` | Which project this repository is |
| `gitgrit project edit --lifecycle … --owner …` | Change a project's lifecycle or owner |
| `gitgrit project standards` | Standards attached to the project |
| `gitgrit project attach <standard>…` / `--all` | Attach standards; they run right away |
| `gitgrit project detach <standard>…` | Detach standards |
| `gitgrit project remove --yes` | Remove the project and its results |
| **Standards** | |
| `gitgrit marketplace list` / `view <pack>` | Browse packs and standards |
| `gitgrit marketplace install <pack>` / `--standard <slug>` | Install a pack, or one standard |
| `gitgrit marketplace update <slug>` | Update an installed standard to the latest version |
| `gitgrit standard list` / `view <id>` | Standards in the workspace |
| `gitgrit standard create` / `edit` / `delete` | Write your own ([Writing Standards](standards.md)) |
| `gitgrit standard test my_standard.py` | Dry-run a standard you're writing, in the sandbox |
| `gitgrit standard enable` / `disable <standard>` | Turn a standard on or off everywhere |
| **Results** | |
| `gitgrit health` | The project's score, standard by standard |
| `gitgrit check --wait` | Run the standards on the branch's latest commit; exit 1 if any fail |
| `gitgrit branches` / `commits` / `commit <sha>` | Results per branch and commit |
| `gitgrit api <path>` | Call any endpoint of the [public API](https://app.gitgrit.dev/api/v1/docs/) |

Standards can be named (`"README Exists"`) or given by id. Add `--json` to any command for the raw API response, and `--help` for all its options.

## In CI

Create a workspace token in **Workspace Settings** → **API Tokens** and save it as the `GITGRIT_TOKEN` secret. A workspace token can do everything a member can, except manage connections.

Fail the build when standards fail:

```yaml
- run: curl -fsSL https://gitgrit.dev/install.sh | sh
- run: ~/.local/bin/gitgrit check --branch "$GITHUB_REF_NAME" --sha "$GITHUB_SHA" --wait
  env:
    GITGRIT_TOKEN: ${{ secrets.GITGRIT_TOKEN }}
```

Use `--fail-under 80` to fail on the score instead of on any failing standard.

## Self-hosted GitGrit

Point the CLI at your instance once, and it stays the default:

```sh
gitgrit auth login --host gitgrit.example.com
gitgrit auth status   # every instance you're signed in to
```

`gitgrit update` moves to the newest release.
