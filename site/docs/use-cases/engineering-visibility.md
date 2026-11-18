---
title: "Engineering visibility for every repository"
description: "A clear engineering dashboard for managers: every repository graded A+ to F, the reason behind each grade, and an architecture map. No chasing people."
---

<p class="gg-uc-page-eyebrow" markdown>:material-view-dashboard-outline: Use case · Engineering visibility</p>

# Engineering visibility: know where every repository stands

Engineering visibility means knowing, without asking anyone, whether each repository meets the standards your team agreed on. GitGrit gives you a clear **engineering dashboard built for managers**, detailed pages for every **project and standard**, and an **architecture map** of how your services fit together. All in **one tool**, with no spreadsheets and **no chasing people** for status.
{ .gg-uc-lead }

## The problem

With three repositories you know everything. **With thirty, you know what people tell you.** Simple questions get hard to answer:

- How many of our repositories have **CI, a linter and a clear owner**?
- Which teams are **drifting** from the way we agreed to build?
- Is our **repository health** getting better or worse?
- What do I tell the board when they ask about **technical debt**?

So you ask team leads, keep a spreadsheet, or find out when something breaks.

## How GitGrit gives you visibility

### An engineering dashboard built for managers

The dashboard works like a car's: **instruments** for project health and this week's checks, and **warning lights** that turn on only when something needs you, with the projects behind them and why. Every repository has a **grade from A+ to F**, so one glance shows where things stand.

### Detailed pages for every project and standard

Open any **project** to see **which standards pass, which fail and exactly why**, per branch and per commit. Open any **standard** to read exactly what it checks, its code, and every version of it: who changed what, and when. A grade you can't explain is a number. A grade with a reason is a to-do list.

### An architecture map

Group repositories into **stacks**, the systems they make up, and the dashboard draws an **architecture map**: your stacks, **the dependencies between them**, and the health of each one. You see where the risk sits in your architecture, not only in a list.

### One tool, no chasing

Visibility, standards and enforcement live **in one place**. Nobody has to fill in a status report, and you don't have to **chase team leads** for an answer the dashboard already has.

### Trends across the organization

The [analytics dashboard](../features/analytics.md) shows the **trend across all repositories**, scores by area (quality, CI/CD, documentation, AI) and the standards that fail most often. You see drift early, and you can show progress.

### Visible to everyone, not only to you

Each team sees its own grades. A [compliance badge](../features/badges.md) in the README shows a repository's grade where developers already look.

## Engineering visibility vs. engineering metrics

DORA dashboards and engineering metrics tools measure **how fast** you ship. GitGrit shows **how well each repository is built** against your own standards. They answer different questions, and most growing teams need both.

## Why repositories, not a service catalog

Developer portals grade services in a **catalog you have to build first**. GitGrit starts from your repositories: connect GitHub or GitLab and you'll see **grades within minutes**. See how GitGrit compares to [Port](../compare/gitgrit-vs-port.md) and [OpsLevel](../compare/gitgrit-vs-opslevel.md).

## FAQ

### What is engineering visibility?
Engineering visibility is a clear, current view of how your codebase is built across every repository and team, without collecting status by hand. In GitGrit it is a grade per repository, the reason behind it, and the trend over time.

### Is this about measuring developers?
No. GitGrit **grades repositories**, not people. It never ranks individual developers.

### What goes into a repository's grade?
The standards attached to that repository, weighted by importance: **Required**, **Major** or **Minor**. A failing Required standard fails the repository.

### How is this different from a code quality tool like SonarQube?
Code quality tools analyze the code inside one repository. GitGrit checks **your own engineering standards across all repositories**: is there CI, a CODEOWNERS file, a supported runtime, current agent instructions.

### Can I start with a few repositories?
Yes. Start with one repository and add the rest when you're ready.

## Related

- [Engineering governance: decide which standards apply where](engineering-governance.md)
- [Standardize engineering across every repository](engineering-standardization.md)

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20engineering%20visibility).
