---
title: "GitGrit vs OpenSSF Scorecard"
description: "OpenSSF Scorecard scores a shared set of open-source security checks from 0 to 10. GitGrit checks the standards your team chooses and grades each repository A+ to F."
---

# GitGrit vs OpenSSF Scorecard

*Last updated 2026-11-20.*

**The short answer:** OpenSSF Scorecard measures the security health of open-source projects with a fixed set of checks. GitGrit checks every repository, public or private, against the standards *your* team chooses, security included, and grades each one A+ to F on every push.

## Who each one fits

**OpenSSF Scorecard fits you if** you want a shared security reading of an open-source project: the same checks a dependency's consumers can look up, with public results and a badge.

**GitGrit fits you if** you want your own standards, security included, checked on the repositories you connect, including private ones, with a grade you can track over time.

Scorecard is the better fit when the question is how a public project looks to the rest of the ecosystem. GitGrit does not publish that kind of score. Many maintainers will want both.

## At a glance

| | OpenSSF Scorecard | GitGrit |
|---|---|---|
| What it is | An automated tool that scores security heuristics of open-source projects, so maintainers can improve them and consumers can judge dependencies. The project says it is not a one-size-fits-all requirement. [What is Scorecard?](https://github.com/ossf/scorecard#what-is-scorecard) | Engineering standards platform |
| What it checks | Scorecard's own checks, including branch protection, code review, pinned dependencies, SAST, and known vulnerabilities. OpenSSF maintains the list, and it changes. A team does not get a private ruleset. [Checks](https://github.com/ossf/scorecard#scorecard-checks) | Standards your team writes, or a ready-made pack you edit. Security can be one of them. |
| Score | Each check scores 0 to 10. The aggregate is a risk-weighted average: Critical 10, High 7.5, Medium 5, Low 2.5. [Aggregate score](https://github.com/ossf/scorecard#aggregate-score) | A letter from A+ to F for the repository. F means a Required standard failed the newest check of the default branch. |
| Platforms | GitHub and GitLab, including self-hosted GitLab. On GitLab, support is per check. The GitHub Action does not support GitHub Enterprise repositories or forks. [GitLab](https://github.com/ossf/scorecard#using-a-gitlab-repository) [Action](https://github.com/ossf/scorecard-action#scorecards-github-action) | GitHub and GitLab |
| Private repositories | The GitHub Action is free for all public repositories. Private GitHub repositories are supported by the Action when they have GitHub Advanced Security; otherwise the command line can run the scan. Private GitLab projects need an access token. [Action](https://github.com/ossf/scorecard-action#scorecards-github-action) [GitLab](https://github.com/ossf/scorecard#using-a-gitlab-repository) | The repositories you connect. A GitHub App installation, or a GitHub or GitLab token, includes private repositories those credentials can read. |
| When it runs | The GitHub Action supports `push` and a `schedule` on the default branch. `pull_request` and `workflow_dispatch` are experimental. [Action](https://github.com/ossf/scorecard-action#scorecards-github-action) | On every push, pull request, and tag. A standard can limit which events and branches it runs on. |
| Adding a check | New checks are contributions to the Scorecard project. [Add a check](https://github.com/ossf/scorecard/blob/main/checks/write.md) | A Python `evaluate` function in your workspace, or an LLM check when a rule needs judgment. |
| License | Apache License 2.0. [LICENSE](https://github.com/ossf/scorecard/blob/main/LICENSE) | Open source (MIT) and self-hostable, including air-gapped. |

## How they work

### OpenSSF Scorecard

Scorecard runs its checks against a repository and scores each one from 0 to 10. Which checks exist, how they are weighted, and how the aggregate is calculated are opinionated, and the checks are heuristics: the project documents false positives and false negatives. An aggregate score does not say which behaviors a repository does or does not do, because different check results can land on the same average.

The GitHub Action runs on repository changes and can publish results, including a badge, for public repositories. A separate weekly scan covers a large set of public repositories. That scan's API results leave out the CI-Tests, Contributors, and Dependency-Update-Tool checks. You can also run the command line against a GitHub or GitLab repository, including a self-hosted GitLab, with a token.

### GitGrit

Each standard is a Python `evaluate` function. It reads the repository and returns whether it passed, a score from 0 to 100, and a message. A standard that needs judgment can take an `llm` argument and call a model the workspace has configured. Standards run in an isolated sandbox. You choose which standards attach to which projects, on which events and branches, and whether each one is Required, Major, or Minor.

The repository's grade is the newest check of its default branch, shown as a letter. A Required failure is an F. A low average with no Required failure is a D, not an F. The standard's own message says why a check failed. You can start from a pack, including Security Essentials, and edit the copy in your workspace.

## Using them together

Scorecard answers "how does this public project score on the security checks the ecosystem shares?" GitGrit answers "does this repository meet the standards our team wrote?" A public repository can show a Scorecard badge and still be graded in GitGrit on rules Scorecard does not have.

## FAQ

### Does GitGrit replace OpenSSF Scorecard?

No. Scorecard is a shared security score for open-source projects, with public results other people can look up. GitGrit checks the standards you choose on the repositories you connect. It does not publish an ecosystem-wide security score. Teams that maintain public projects often want both.

### Can OpenSSF Scorecard check private repositories?

Yes, with limits that depend on how you run it. The GitHub Action is free for all public repositories. It supports private repositories that have GitHub Advanced Security. Private repositories without that can be scanned with the Scorecard command line. Private GitLab projects need a GitLab access token (`read_api`, `read_user`, and `read_repository`). The GitHub Action does not support GitHub Enterprise repositories, and it does not run on forks.

### Can I define my own Scorecard checks?

Not as a private ruleset. Scorecard runs its own checks. Adding a check means contributing one to the Scorecard project. In GitGrit, a standard is code in your workspace, or a pack you install and then edit.

### Which platforms does each one support?

Scorecard documents GitHub and GitLab, including self-hosted GitLab. On GitLab, some checks are supported, some are marked validating, and some are unsupported, including Dangerous-Workflow, SAST, and Token-Permissions. GitGrit supports GitHub and GitLab.

### Does GitGrit only check security?

No. Security can be one of the standards. A ready-made Security Essentials pack checks for secrets in the tree. The rest of a grade is whatever else you attach, such as a README, CI, or a lockfile.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%20vs%20OpenSSF%20Scorecard).

## Sources

- [OpenSSF Scorecard: README](https://github.com/ossf/scorecard#what-is-scorecard)
- [OpenSSF Scorecard: checks](https://github.com/ossf/scorecard#scorecard-checks)
- [OpenSSF Scorecard: check documentation](https://github.com/ossf/scorecard/blob/main/docs/checks.md)
- [OpenSSF Scorecard: aggregate score](https://github.com/ossf/scorecard#aggregate-score)
- [OpenSSF Scorecard: GitLab](https://github.com/ossf/scorecard#using-a-gitlab-repository)
- [OpenSSF Scorecard: adding a check](https://github.com/ossf/scorecard/blob/main/checks/write.md)
- [OpenSSF Scorecard: license](https://github.com/ossf/scorecard/blob/main/LICENSE)
- [Scorecard GitHub Action](https://github.com/ossf/scorecard-action#scorecards-github-action)
