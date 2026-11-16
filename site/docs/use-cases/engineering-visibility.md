---
title: "Engineering visibility and control for CTOs and engineering leaders"
description: "Know where every repository stands and decide what standards your teams follow. GitGrit gives engineering leaders one screen with every repository's grade, the exact reason, and control over what runs where."
---

<p class="gg-uc-page-eyebrow" markdown>:material-view-dashboard-outline: Use case · For CTOs and engineering leaders</p>

# Lead with visibility and control

**The short answer:** as your organization grows, the full picture arrives in pieces: dailies, status updates, a question in Slack. GitGrit gives you one screen with every repository's grade against the standards you set, the exact reason behind each grade, and the controls to decide what matters, where, and how much.

## The problem

With three repositories you know everything. With thirty, you know what people tell you. Simple questions get hard to answer:

- How many of our repositories have CI, a linter and a clear owner?
- Which teams are drifting from the way we agreed to build?
- Is it getting better or worse?

So you ask team leads, keep a spreadsheet, or find out when something breaks. And even when you know what should change, the standards live in a wiki, so there's no lever to pull.

## See where everything stands

### One grade per repository

Every repository gets a grade from **A+ to F**, based on the standards you chose for it and how much each one matters. One glance shows where things stand, before anyone has to tell you.

### A dashboard that tells you what needs you

The dashboard reads like a car's: instruments for project health and this week's checks, warning lights that turn on only when something needs you, and the projects that need attention, with why.

### The reason, not just the score

Open any repository to see which standards pass, which fail and exactly why, per branch and per commit.

### Trends over time

The [analytics dashboard](../features/analytics.md) shows the trend across all repositories, scores by area (quality, CI/CD, documentation, AI) and the standards that fail most often. You see drift early, and you see your progress.

## Decide what matters

### Your standards, in one place

Your standards live in one workspace as short, readable code, not in a wiki. Start from ready-made packs, then adapt them or [write your own](../getting-started/standards.md).

### What runs where

Choose which standards apply to each project, on which branches and events: every push, pull requests only, or only the main branch.

### How much each one matters

Mark each standard **Required**, **Major** or **Minor**, per project. A failing Required standard fails the project; the rest count toward its grade. The same standard can be Required for your core services and Minor for an internal tool.

### Every change on record

Standards are [versioned](../features/versioning.md): who changed what, when, and a one-click revert.

## Why repositories, not a service catalog

Developer portals grade services in a catalog you have to build and maintain first. GitGrit starts from your repositories: connect GitHub or GitLab and you'll see grades within minutes. Already using a portal? See how GitGrit compares to [Port](../compare/gitgrit-vs-port.md) and [OpsLevel](../compare/gitgrit-vs-opslevel.md).

## FAQ

### Is this about measuring developers?
No. GitGrit grades repositories against the standards your team agreed on. It doesn't rank individual developers.

### What goes into the grade?
The standards attached to that repository, weighted by importance: Required, Major or Minor.

### Does this add process for my teams?
No meetings and no checklists. The checks run on their own, and developers see the result on their own commits.

### Can I start with a few repositories?
Yes. Start with one repository and add the rest when you're ready.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20visibility%20and%20control).
