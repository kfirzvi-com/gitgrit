# Quick Start

From sign-in to your first health score in about 10 minutes.

**You'll need:** a GitHub organization (or GitLab group) where you can install apps, and one or two repositories to try it on.

## 1. Request access

Go to [app.gitgrit.dev](https://app.gitgrit.dev) and sign in with Google, GitHub, GitLab, or an email and password.

![Sign in to GitGrit](../images/quickstart/01-sign-in.jpg){ .gg-shot .gg-shot--narrow loading=lazy }

Tell us a little about you and your team, then **Request access**. Signing up with email? Confirm your address from the email we send first.

![Tell us about you](../images/quickstart/02-request-access.jpg){ .gg-shot .gg-shot--narrow loading=lazy }

We'll email you as soon as you're in. Sign in the same way you just did, and you land in your company's workspace.

## 2. Connect your git platform

On the empty dashboard, click **Connect git platform**.

![An empty workspace](../images/quickstart/04-empty-workspace.jpg){ .gg-shot loading=lazy }

Click **Install GitHub App**.

![Install the GitHub App](../images/quickstart/05-install-github-app.jpg){ .gg-shot loading=lazy }

GitHub asks where to install GitGrit:

1. Pick your organization.
2. Choose **Only select repositories** and pick the repos you want to try. You can add more later from GitHub.
3. Click **Install**. You're sent back to GitGrit.

!!! tip "No admin rights on the org?"
    GitHub sends the install to an org owner for approval. Once they approve, click **Install GitHub App** again.

??? note "GitLab, or using a token instead"
    Pick **GitLab** (or GitHub) in the same form, paste a personal access token, and click **Add Connection**. **How to generate a token?** lists the permissions it needs.

## 3. Install standards

A standard is a check that runs on every commit, like "has a README" or "has CI configured". Start from a ready-made pack: open **Marketplace**.

![The Standard Marketplace](../images/quickstart/06-marketplace.jpg){ .gg-shot loading=lazy }

**Repository Hygiene** is a good first pack: it works on any repo, whatever the language. Open it and click **Install All**.

![Install a pack](../images/quickstart/07-install-pack.jpg){ .gg-shot loading=lazy }

## 4. Add your repositories

Go to **Projects** → **Add Project**, pick your connection, and click **Select** next to a repository.

![Pick a repository](../images/quickstart/08-pick-repo.jpg){ .gg-shot loading=lazy }

Under **Attach standards**, click **Select all**, then **Add Project**.

![Attach standards](../images/quickstart/09-attach-standards.jpg){ .gg-shot loading=lazy }

!!! warning "Attach at least one standard"
    Only attached standards run on a project, and none are attached by default. You can attach more later from the project's **Standards** tab.

Repeat for each repository you want to try.

## 5. See your score

The standards start running as soon as the project is added. Within a minute the project page shows its health score:

![A project's health score](../images/quickstart/10-project-score.jpg){ .gg-shot loading=lazy }

Open **Results** to see what passed, what failed, and why:

![Results per standard](../images/quickstart/11-results.jpg){ .gg-shot loading=lazy }

From now on every push re-runs the standards automatically. To run them on demand, click **Run on latest commit**.

## 6. Use it from your terminal

The `gitgrit` CLI shows the same results from your terminal, scripts, and CI. Install it (`ggr` works as a short name) and sign in through your browser:

```sh
curl -fsSL https://gitgrit.dev/install.sh | sh
gitgrit auth login
gitgrit workspace use "Acme"   # only if you're in several workspaces
```

Project commands work on the repository you're in:

```console
$ cd ~/src/auth-service
$ gitgrit health
gitgrit-demo-auth-service · project health
Score 30 · critical · 1 passed, 4 failed, 0 errored

STATUS    SCORE  STANDARD                   COMMIT   RAN     MESSAGE
✓ passed  100    README Exists              1fc38e8  1m ago  README found: README.md
✗ failed  0      License File               1fc38e8  1m ago  No LICENSE file found in repository
✗ failed  50     GitGrit Badge in README    1fc38e8  1m ago  No GitGrit badge found in README. Add the compliance badge …
✗ failed  0      CODEOWNERS File            1fc38e8  1m ago  No CODEOWNERS file found
✗ failed  0      CI Configuration Required  1fc38e8  1m ago  No CI/CD configuration found
```

| Command | What it does |
|---|---|
| `gitgrit project list` | Projects in your workspace |
| `gitgrit health` | This repo's health score, standard by standard |
| `gitgrit check --wait` | Runs the standards on the branch's latest commit and exits 1 if any fail |
| `gitgrit standard list` | Standards installed in your workspace |
| `gitgrit standard test my_standard.py` | Dry-runs a standard you're writing, in the sandbox |

Add `--json` to any command to get the raw API response.

### In CI

Create a workspace token in **Workspace Settings** → **API Tokens**, save it as the `GITGRIT_TOKEN` secret, and fail the build when standards fail:

```yaml
- run: curl -fsSL https://gitgrit.dev/install.sh | sh
- run: ~/.local/bin/gitgrit check --branch "$GITHUB_REF_NAME" --sha "$GITHUB_SHA" --wait
  env:
    GITGRIT_TOKEN: ${{ secrets.GITGRIT_TOKEN }}
```

Use `--fail-under 80` to fail on the score instead of on any failing standard.

## What's next?

- [Workspaces & Members](workspaces.md): invite your team and set roles
- [Writing Standards](standards.md): encode your own team's rules
- [Standard Marketplace](../features/marketplace.md): Docker, Node.js, Python, security, and more
- [Compliance Badges](../features/badges.md): show the score in your README
