---
title: "Enforce engineering standards on every commit"
description: "GitGrit checks every push, pull request and tag across every repository, flags the exact commit that broke a standard, and can fail your CI build."
---

<p class="gg-uc-page-eyebrow" markdown>:material-source-commit: Use case · Enforce engineering standards</p>

# Enforce engineering standards on every commit

A standard nobody checks is a suggestion. GitGrit **enforces your engineering standards automatically**: it checks **every push, pull request and tag, on every branch**, flags the **exact commit** that broke a standard while it still costs minutes to fix, and can **fail the CI build** when a Required standard fails.
{ .gg-uc-lead }

## The problem

Your team agreed on how to build: every service has CI, dependencies are locked, Docker images are pinned, every repository has a linter. Then deadlines get closer, and a new repository skips a step. **Nobody notices, because nothing is checking.**

- **Code review doesn't catch it.** Reviewers look at the lines that changed, not at what's missing.
- **Linters don't catch it.** They're configured per repository, and only where someone set them up.
- **Repositories nobody touches are never reviewed at all.**

So the gap is found months later, in an incident or a customer demo, when it has already spread to ten repositories.

## How GitGrit enforces your standards

### Every change is checked

GitGrit runs your standards on **every push, pull request and tag, on every branch**, triggered by GitHub or GitLab. Each check runs **in an isolated sandbox** and gets **the same answer every time**.

### Flagged on the commit that introduced it

When a check fails, GitGrit shows **the commit, the branch and the exact reason**, so the fix is obvious to whoever made the change, on the day they made it.

### Fail the build when it matters

Mark a standard **Required** and a failure fails the project. Add one step to your pipeline and **the build fails too**:

```yaml
- run: curl -fsSL https://gitgrit.dev/install.sh | sh
- run: ~/.local/bin/gitgrit check --branch "$GITHUB_REF_NAME" --sha "$GITHUB_SHA" --wait
  env:
    GITGRIT_TOKEN: ${{ secrets.GITGRIT_TOKEN }}
```

Add `--fail-under 90` to also fail any build that drops **below an A**. See the [CLI guide](../getting-started/cli.md).

### Strict where it counts, gentle elsewhere

**Required** standards fail the project. **Major** and **Minor** ones lower the grade without blocking anyone. You choose per project, so enforcement never becomes friction where it isn't needed.

### Standards that are worth enforcing

A few examples from the [marketplace](../features/marketplace.md):

| Standard | What it catches |
|---|---|
| CI Configuration Required | A repository with no CI pipeline at all |
| Dependency Lockfile Exists | Builds that resolve different versions on every machine |
| No :latest Tag in Dockerfile | Images that change under you without a code change |
| No Secrets in Code | `.env` files, private keys and credential files committed to Git |
| Linter Configured | A repository where nobody runs the linter |

## FAQ

### How do I enforce coding standards across many repositories?
Write each standard once as code, attach it to every repository it applies to, and let it run on every push. GitGrit does this from one workspace, so you don't copy configuration into each repository.

### We already have linters and CI. Isn't that enough?
Linters check code style inside one repository. GitGrit checks **your own rules across all repositories**, including whether each repository has CI and a linter in the first place.

### Can GitGrit block a merge?
Yes, through your CI. The `gitgrit check --wait` step fails when a Required standard fails, so a branch protection rule that requires that CI job blocks the merge.

### Do I need to change every CI pipeline?
No. GitGrit runs the checks itself, triggered by your Git host. The CI step is optional, for teams that want to fail the build.

### Which Git hosts are supported?
GitHub and GitLab. You can connect both to one workspace.

## Related

- [Engineering governance: decide which standards apply where](engineering-governance.md)
- [Keep AI-written code on your standards](ai-coding-standards.md)

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20enforcing%20standards).
