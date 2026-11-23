---
description: "Check each app, service and library of a monorepo as its own GitGrit project: its own standards, score, stacks and map node, rooted at its directory."
---

# Monorepos

A monorepo holds several things you build and ship on their own: a web app, an API, a worker, a shared library. In GitGrit each one can be a **project of its own**, rooted at its directory inside the repository. It gets its own standards, its own score and history, its own stacks and its own card on the [stack map](../features/stacks.md#the-stack-map).

## Add a project at a path

When you [add a repository](projects.md#add-a-repository), fill in **Root path** with the directory the project lives in, e.g. `apps/web`. Leave it empty for the whole repository. A repository that is already a project can be added again at another path: the search shows the paths it is a project at already.

From the terminal:

```sh
gitgrit project add acme/shop                      # the whole repository
gitgrit project add acme/shop --path apps/web
gitgrit project add acme/shop --path services/api
```

Or over the API: `POST projects/` with `"root_path": "apps/web"` ([REST API](../api/rest.md)).

## Suggested projects

Add the whole repository first. When GitGrit maps its dependencies (with your workspace's [AI model](../features/ai.md#providers-and-roles)), it lists the apps, services and libraries it finds inside it as **suggested projects** on the project page, under **In this repository**. **Add** one, or **Add all**: each becomes a project at its directory, with the name, description and tech labels GitGrit found.

## What changes for a project at a path

- **Standards read its directory.** A standard that checks `package.json` or `Dockerfile` reads `apps/web/package.json`. Standards that need a file at the repository root (a workspace lockfile, CI config) can still read it with `get_repository_file_content` ([ProjectContext](../api/project-context.md)).
- **Repository-wide standards go on the whole-repository project.** CODEOWNERS, CI config, LICENSE and README live at the root: attach them to the project with no root path, and the app and service standards to the projects at their paths.
- **A push runs only the projects it touched.** A push that changes `services/api/` runs the whole-repository project and `services/api`, not `apps/web`. When GitGrit can't tell what a push changed, it runs them all.
- **Its commits are the ones that touched its directory**, and its score follows them.
- **Its languages are its own**, counted from its files, so language-specific standards fit it.
- **One webhook per repository**, however many projects it holds.
- **The CLI picks the project you stand in.** Inside `apps/web` of a clone, `gitgrit health` is about the `apps/web` project.
- Each project counts once towards your plan's projects ([Pricing](../pricing.md)).
