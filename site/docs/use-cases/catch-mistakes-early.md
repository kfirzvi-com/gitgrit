---
title: "Enforce engineering standards on every commit"
description: "Catch engineering mistakes on the first commit, not months later in production. GitGrit checks your engineering standards on every push, pull request and tag, across every repository."
---

<p class="gg-uc-page-eyebrow" markdown>:material-source-commit: Use case · Enforce engineering standards</p>

# Catch mistakes on the first commit

**The short answer:** a standard that was missing or ignored from the start usually gets found months later, when it breaks, in a customer demo or right before a deadline. By then it's in many places. GitGrit checks your standards on every push, so the mistake is flagged on the commit that introduced it, while it still costs minutes to fix.

## The problem

Your team agreed on how to build: every service has CI, dependencies are locked, Docker images are pinned, every repository has a linter. Then the team grows, deadlines get closer, and a new repository skips a step. Nobody notices, because nothing is checking.

Code review doesn't catch it either. Reviewers look at the lines that changed, not at what's missing, and they don't look at repositories nobody is touching.

## How GitGrit helps

### Your standards, checked on every change

Each standard is a short, readable piece of code. GitGrit runs it on every push, pull request and tag, on every branch, in an isolated sandbox, and gets the same answer every time.

A few examples from the marketplace:

| Standard | What it catches |
|---|---|
| CI Configuration Required | A repository with no CI pipeline at all |
| Dependency Lockfile Exists | Builds that resolve different versions on every machine |
| No :latest Tag in Dockerfile | Images that change under you without a code change |
| Linter Configured | A repository where nobody runs the linter |

### Decide what matters most

Mark each standard **Required**, **Major** or **Minor** for each project. A failing Required standard fails the project. The rest count toward its grade.

### The exact reason, right away

When a check fails, GitGrit shows the commit, the branch and the exact reason, so the fix is obvious to whoever made the change.

### Roll out new standards safely

Dry-run a new or changed standard to see which repositories would fail, then roll it out everywhere at once. Standards are [versioned](../features/versioning.md), so you can see how each one evolved.

## FAQ

### We already have linters and CI. Isn't that enough?
Linters check one repository's code style, configured separately in each repository. GitGrit checks your own rules across all repositories, including whether each repository has CI and a linter in the first place.

### Do I need to change my CI pipelines?
No. GitGrit runs the checks itself, triggered by your Git host, so there's nothing to add to each pipeline.

### Which Git hosts are supported?
GitHub and GitLab. You can connect both to one workspace.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20catch%20mistakes%20early).
