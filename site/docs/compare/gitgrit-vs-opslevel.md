---
title: GitGrit vs OpsLevel: engineering standards compared
description: OpsLevel is an internal developer portal with rubrics, scorecards and campaigns over a service catalog. GitGrit checks every repository against standards written as code. Here's how they differ.
---

# GitGrit vs OpsLevel

*Last updated 2026-10-29.*

**The short answer:** OpsLevel is an internal developer portal. Its rubric and scorecards grade services in a catalog, using a set of built-in check types. GitGrit checks every repository against standards you write as code, on every push, and gives each repository a grade.

## Who each one fits

**OpsLevel fits you if** you want a service catalog with ownership, maturity levels and campaigns to drive improvements across many teams and services.

**GitGrit fits you if** you want any engineering standard you can express in code checked on every repository, without setting up a catalog first.

## At a glance

| | OpsLevel | GitGrit |
|---|---|---|
| What it is | Internal developer portal | Engineering standards platform |
| What gets graded | Services (components) in a catalog | Repositories (projects) |
| How a check is defined | Built-in check types (file, grep, tags, packages, and more), or JSON you send from your own pipeline | Code (Python) that reads the repository, or an LLM check when a rule needs judgment |
| Where checks run | OpsLevel evaluates its checks; custom logic runs in your own pipeline | In GitGrit's isolated sandbox, with nothing to maintain on your side |
| When it's checked | Continuously, as OpsLevel scans connected repositories | On every push, pull request and tag, per branch |
| Grade | Levels such as Bronze, Silver and Gold | A+ to F, with Required, Major and Minor standards |
| Open source | No | Yes (MIT), self-hostable, including air-gapped |

## How they work

### OpsLevel

OpsLevel catalogs your services and connects repositories to them. Its rubric is a grid of categories and levels: a service reaches a level when it passes every check in it. Checks come from a set of types such as repository file checks, text search, tags, package versions and branch protection. For anything else, custom event checks evaluate JSON that you send from your own systems. Campaigns roll out a new check across teams with a deadline.

### GitGrit

In GitGrit, each standard is a short, readable piece of code that checks the repository directly. Standards run in an isolated sandbox on every push, pull request and tag. You choose which standards apply to which projects, branches and events, and how much each one matters. Every repository gets a grade from A+ to F, with the exact reason when something fails. Standards are versioned, and you can dry-run a change before rolling it out.

## FAQ

### Does GitGrit replace OpsLevel?
Not as a portal. GitGrit doesn't offer a service catalog or ownership views. It focuses on checking every repository against your engineering standards.

### Can I write a check that isn't a built-in type?
In GitGrit, every standard is code, so you aren't limited to a menu of check types, and you don't need to run your own pipeline to feed results in.

### Does GitGrit check every branch?
Yes. GitGrit records results per commit and per branch, and you decide which branches and events each standard applies to.

### How do I get started?
Connect a repository from GitHub or GitLab, install a ready-made pack of standards, and you'll see a grade within minutes.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%20vs%20OpsLevel).

## Sources

- [OpsLevel: getting started with rubrics](https://docs.opslevel.com/docs/getting-started-with-rubrics)
- [OpsLevel: repository file checks](https://docs.opslevel.com/docs/repo-file-checks)
- [OpsLevel: custom event checks](https://docs.opslevel.com/docs/custom-event-checks)
- [OpsLevel: campaigns](https://docs.opslevel.com/docs/getting-started-with-campaigns)
