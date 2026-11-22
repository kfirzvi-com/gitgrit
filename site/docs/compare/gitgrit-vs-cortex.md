---
title: "GitGrit vs Cortex: scorecards and standards"
description: "Cortex scorecards grade catalog entities on a schedule, with rules in CQL or from integrations. GitGrit grades repositories from GitHub or GitLab with standards written as code."
---

# GitGrit vs Cortex

*Last updated 2026-11-20.*

**The short answer:** Cortex scores services in a developer portal you set up and maintain. GitGrit grades repositories directly from GitHub or GitLab, with standards written as code, so you see where every repo stands in minutes.

## Who each one fits

**Cortex fits you if** you want an internal developer portal: a catalog of entities, ownership, scorecards, initiatives with deadlines, and reports, and you have people to model and maintain that catalog.

**GitGrit fits you if** you want repository standards checked from GitHub or GitLab without building a service catalog first.

Cortex is the better fit when the thing you need to grade is a service in a catalog, such as its owner, runbook, monitor, or latency, including things that are not files in a repository. GitGrit does not provide a software catalog, initiatives, or engineering-intelligence reports.

## At a glance

| | Cortex | GitGrit |
|---|---|---|
| What it is | An internal developer portal. A scorecard is a set of rules measured against entities in the catalog. Pricing is per-seat and quoted for the size of the organization. [Scorecards](https://docs.cortex.io/standardize/scorecards) [Pricing](https://www.cortex.io/pricing) | Engineering standards platform |
| What gets graded | Entities you define, such as services. A scorecard applies to an entity type, and you can narrow it with groups or a CQL expression. Every entity has a YAML descriptor. [Scorecards](https://docs.cortex.io/standardize/scorecards) [Entity YAML](https://docs.cortex.io/ingesting-data-into-cortex/entities-overview/entities/yaml) | Repositories you connect from GitHub or GitLab |
| How a rule is written | A pre-configured rule from an integration you have set up, or a CQL expression you write. [CQL](https://docs.cortex.io/standardize/cql) | A Python `evaluate` function that reads the repository, or an LLM check when a rule needs judgment |
| Where rule data comes from | Entity metadata inside Cortex, or live data from integrations. The GitHub and GitLab integrations can attach a repository to an entity. [GitHub](https://docs.cortex.io/ingesting-data-into-cortex/integrations/github) [GitLab](https://docs.cortex.io/ingesting-data-into-cortex/integrations/gitlab) | The repository itself, read in an isolated sandbox when the standard runs |
| When it's checked | On a schedule. The default evaluation window is every 4 hours. [Scorecards](https://docs.cortex.io/standardize/scorecards) | On every push, pull request, and tag |
| Git data | For GitHub, GitLab, and Bitbucket, GitOps reads `cortex.yaml` anywhere on the default branch. For Azure DevOps, the documented place is the repository root of the default branch. [GitOps](https://docs.cortex.io/configure/gitops/using-gitops-for-cortex) | Results are kept per commit and per branch. A standard can limit events and branch patterns. |
| Grade | Levels such as Bronze, Silver, and Gold, or points on each rule, or points within levels. [Levels or points](https://docs.cortex.io/standardize/scorecards) | A letter from A+ to F. Required, Major, and Minor change how a standard affects that grade. A Required failure is an F. |
| Driving a fix | An Initiative adds a deadline, owners, and reminders on top of a scorecard. Reports roll scores up. [Initiatives](https://docs.cortex.io/improve/initiatives) | The grade, and the failing standard's message, on the repository. |

## How they work

### Cortex

You define entities in the catalog, in the UI or as YAML, and integrations fill in data. A scorecard applies to a set of those entities. Each rule passes or fails. Rules can use a form built from an integration, or CQL when the rule spans sources or is specific to your organization. You can exempt an entity from a rule, filter a rule to certain groups, and schedule a rule so it is visible before it counts.

Levels group rules into ordered tiers. An entity reaches a level only after passing every rule in that level and below. Points give each rule a weight instead, and a scorecard can use both. Saving a change starts a reevaluation. The default window for rechecking every rule against every entity is four hours. Initiatives sit on top of a scorecard when you want a deadline and notifications. Scorecards can also be managed as code or through the API.

### GitGrit

Each standard is a Python `evaluate` function that reads the repository and returns whether it passed, a score from 0 to 100, and a message. A standard that needs judgment can take an `llm` argument. Standards run in an isolated sandbox on the events you select: push, pull request, and tag. You attach them per project and mark each one Required, Major, or Minor.

The grade shown for a repository is the newest check of its default branch. A Required failure is an F. A low average with no Required failure is a D. There is no catalog to model before the first grade: connect a repository and attach standards, including a ready-made pack.

## Using them together

They can sit side by side. Cortex can stay the catalog people browse for services, ownership, and deadlines. GitGrit can be where repository standards are checked as code, including on branches and events Cortex's default-branch GitOps sync does not cover.

## FAQ

### Does GitGrit replace Cortex?

No. Cortex is a developer portal: a catalog, ownership, scorecards, initiatives, and reports. GitGrit does not offer those. It checks repositories against standards written as code.

### Do I need a catalog before the first grade?

In Cortex, a scorecard measures entities, and each entity has a descriptor. In GitGrit you connect a repository from GitHub or GitLab and attach standards. Nothing else has to be modeled first.

### How often does each one recheck?

Cortex rechecks rules on a schedule. The default evaluation window is every 4 hours. GitGrit runs the standards that apply on each push, pull request, and tag.

### Can a rule read the repository itself?

A GitGrit standard is code that reads the repository in the sandbox, so it can check files, configuration, and history. A Cortex rule reads entity metadata or integration data, including what the GitHub and GitLab integrations sync, and you can write that rule in CQL.

### How is Cortex priced?

Cortex uses a per-seat model. The quote depends on the size of the organization.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%20vs%20Cortex).

## Sources

- [Cortex: scorecards](https://docs.cortex.io/standardize/scorecards)
- [Cortex: CQL](https://docs.cortex.io/standardize/cql)
- [Cortex: initiatives](https://docs.cortex.io/improve/initiatives)
- [Cortex: entity YAML](https://docs.cortex.io/ingesting-data-into-cortex/entities-overview/entities/yaml)
- [Cortex: GitHub integration](https://docs.cortex.io/ingesting-data-into-cortex/integrations/github)
- [Cortex: GitLab integration](https://docs.cortex.io/ingesting-data-into-cortex/integrations/gitlab)
- [Cortex: GitOps](https://docs.cortex.io/configure/gitops/using-gitops-for-cortex)
- [Cortex: pricing](https://www.cortex.io/pricing)
