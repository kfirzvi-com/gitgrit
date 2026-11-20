---
title: "GitGrit vs Backstage scorecards"
description: "Backstage scorecards are plugins on a portal you run, including Tech Insights and Spotify Soundcheck. GitGrit grades connected repositories from A+ to F."
---

# GitGrit vs Backstage scorecards

*Last updated 2026-11-20.*

**The short answer:** Backstage scorecards need a Backstage portal, plugins and a team to run them. GitGrit is a ready-made, open-source standards platform: connect your repos, pick standards, and get an A+ to F grade for each one.

## Who each one fits

**Backstage scorecards fit you if** you already run, or want to run, a Backstage developer portal, and you want grades next to the catalog, templates, and docs your platform team operates.

**GitGrit fits you if** you want a grade per repository without standing up a portal, installing a scorecard plugin, and keeping a catalog model current.

Backstage is the better fit when the portal is the point: one place for service ownership, scaffolding, and documentation, with scorecards as one plugin among many. GitGrit is not a developer portal and will not replace Backstage for a team that needs that.

## At a glance

| | Backstage scorecards | GitGrit |
|---|---|---|
| What they are | Plugins on a Backstage portal. Out of the box, Backstage ships a software catalog, software templates, and TechDocs. Scorecards are not in that list. [What is Backstage?](https://backstage.io/docs/overview/what-is-backstage/) | Engineering standards platform |
| Open-source plugin | Tech Insights, a community plugin, shows boolean checks as scorecards on catalog entities. Its repository is under the Apache License 2.0. [Tech Insights](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights/README.md) [LICENSE](https://github.com/backstage/community-plugins/blob/main/LICENSE) | Open source (MIT) and self-hostable, including air-gapped |
| Commercial plugin | Spotify Soundcheck adds checks, tracks, levels, and certifications. The plugins are closed source, need a license key, and are sold only as part of the Spotify Plugins for Backstage bundle. [Soundcheck](https://backstage.spotify.com/docs/plugins/soundcheck) [Licensing](https://backstage.spotify.com/docs/plugins/getting-started/) [FAQ](https://backstage.spotify.com/faqs) | One product. Connect repositories and attach standards. It is not a plugin you add to a portal. |
| What gets graded | Catalog entities. Tech Insights evaluates facts about those entities. Soundcheck grades components against checks. [Tech Insights backend](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights-backend/README.md) [Soundcheck](https://backstage.spotify.com/docs/plugins/soundcheck) | Repositories you connect from GitHub or GitLab |
| How a check is defined | Tech Insights: JSON rules over facts, after you register fact retrievers. The documented checker returns boolean results. Soundcheck: rules in a no-code UI or in YAML, combined with Any Of / All Of. [JSON rules](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights-backend-module-jsonfc/README.md) [Soundcheck checks](https://backstage.spotify.com/docs/plugins/soundcheck/core-concepts/checks) | A Python `evaluate` function that reads the repository, or an LLM check when a rule needs judgment |
| Setup before a score | Run Backstage, install the plugin, and model the catalog. Tech Insights fact retrievers are not registered until you configure them. The three built-in retrievers cover entity metadata, ownership, and TechDocs. [Backend](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights-backend/README.md) | Connect GitHub or GitLab and attach standards. A ready-made pack is enough to start. |
| Portal license | Backstage is Apache License 2.0. [LICENSE](https://github.com/backstage/backstage/blob/master/LICENSE) | Open source (MIT) and self-hostable, including air-gapped |

## How they work

### Backstage scorecards

Backstage is a framework you deploy. The catalog is the list of software the portal knows about. Scorecards are added.

Tech Insights is the open-source community plugin that renders checks as scorecards, on an entity tab and on a scorecards page. Facts are collected by fact retrievers. Nothing is collected until you register retrievers in config. Three ship with the plugin: entity metadata, ownership (`spec.owner`), and TechDocs. They run on a cadence you set. A JSON-rules fact checker then evaluates those facts as boolean checks. Repository data is not one of the built-in facts. A custom fact retriever can pull it, which means writing and registering that retriever. The plugin can also expose scorecard data to MCP clients once the actions backend is set up.

Spotify Soundcheck is a different product in the same portal. A check compares an outcome with a standard and passes or fails. Tracks group checks into levels, and a certification is the result of passing every check in a level. Soundcheck is part of Spotify's commercial plugin bundle: closed source, installed with a license key, and not sold on its own.

### GitGrit

Each standard is a Python `evaluate` function that reads the repository and returns whether it passed, a score from 0 to 100, and a message. A standard that needs judgment can take an `llm` argument. Standards run in an isolated sandbox on push, pull request, and tag. You attach them per project and mark each one Required, Major, or Minor.

The grade is a letter from A+ to F for the repository's default branch. A Required failure is an F. You do not run a portal or register fact retrievers to get that grade.

## FAQ

### Does GitGrit replace Backstage?

No. Backstage is a framework for a developer portal: a software catalog, software templates, and TechDocs, plus the plugins you add. GitGrit does not provide that portal. It checks repositories against standards.

### Are scorecards part of Backstage itself?

No. Backstage's own overview lists the catalog, software templates, and TechDocs as what you get out of the box, plus a plugin ecosystem. Scorecards come from plugins. Tech Insights is the open-source community plugin that renders checks as scorecards. Spotify Soundcheck is a separate commercial plugin.

### What do I have to run for Tech Insights?

A Backstage instance, the Tech Insights backend and UI, a fact checker, and fact retrievers configured in `app-config.yaml`. The documented checker is the JSON rules module, and its results are boolean. The three built-in retrievers cover entity metadata, ownership, and TechDocs, and only after you register them. Facts about a Git repository need a retriever you add.

### Is Soundcheck the same as Tech Insights?

No. Tech Insights is the Apache-licensed community plugin. Soundcheck is Spotify's commercial plugin: checks, tracks, levels, and certifications, closed source, and sold only in the Spotify Plugins for Backstage bundle. Using any plugin in that bundle requires a license key.

### Do I need a portal to use GitGrit?

No. You connect repositories from GitHub or GitLab and attach standards. GitGrit does not catalog services, scaffold projects, or host your docs.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%20vs%20Backstage%20scorecards).

## Sources

- [Backstage: what is Backstage?](https://backstage.io/docs/overview/what-is-backstage/)
- [Backstage: license](https://github.com/backstage/backstage/blob/master/LICENSE)
- [Tech Insights UI](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights/README.md)
- [Tech Insights backend](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights-backend/README.md)
- [Tech Insights JSON rules checker](https://github.com/backstage/community-plugins/blob/main/workspaces/tech-insights/plugins/tech-insights-backend-module-jsonfc/README.md)
- [Community plugins license](https://github.com/backstage/community-plugins/blob/main/LICENSE)
- [Spotify Soundcheck](https://backstage.spotify.com/docs/plugins/soundcheck)
- [Spotify Soundcheck: checks](https://backstage.spotify.com/docs/plugins/soundcheck/core-concepts/checks)
- [Spotify Plugins: licensing](https://backstage.spotify.com/docs/plugins/getting-started/)
- [Spotify Plugins: FAQ](https://backstage.spotify.com/faqs)
