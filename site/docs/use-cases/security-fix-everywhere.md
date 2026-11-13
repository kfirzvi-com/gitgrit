---
title: "Make sure a security fix reached every repository"
description: "A vulnerable package or a bad configuration turns up in one repository. Is it anywhere else? GitGrit lets you write a check in minutes, run it across every repository, and track the fix until every one is clean."
---

<p class="gg-uc-page-eyebrow" markdown>:material-shield-check-outline: Use case · Responding to a security issue across repositories</p>

# Make sure a fix reached every repository

**The short answer:** when a vulnerable dependency or a risky configuration is found, the first question is "where else do we have this?" and the second is "are we sure it's fixed everywhere?" With GitGrit you turn the issue into a standard in minutes, run it across every repository, mark it Required, and watch until every repository passes. Then it keeps running, so the issue can't quietly come back.

## The problem

A compromised version of a popular package is announced. Or someone finds a committed config that disables a safety check. You fix it in the repository where you found it. But:

- Nobody knows for sure which other repositories have the same thing.
- Each team says it's fixed, and you have to take their word for it.
- Three months later, a new repository copies the old setup and brings it back.

Security scanners are built to find known vulnerabilities. They aren't built to answer your own question, in your own words, across every repository, today.

## How GitGrit helps

### Turn the issue into a check, in minutes

Every GitGrit standard is a short piece of Python that reads the repository. A check for a compromised package version looks like this:

```python
def evaluate(project):
    lockfile = project.get_file_content("package-lock.json")
    if lockfile and '"example-lib": "4.2.1"' in lockfile:
        return {"passed": False, "score": 0,
                "message": "Uses example-lib 4.2.1. Upgrade to 4.2.2."}
    return {"passed": True, "score": 100, "message": "Not affected"}
```

### See where it is, right away

Run it across every repository at once. In minutes you have the list of affected repositories, with the exact reason for each.

### Track the fix to zero

Mark the standard **Required**. Every affected repository fails until it's fixed, and the dashboard shows how many are left. No spreadsheet, no asking each team.

### Make sure it doesn't come back

The standard keeps running on every push, pull request and tag. A new repository or a copied config that brings the issue back is flagged on that push.

## Where it fits next to your security tools

GitGrit doesn't replace a vulnerability scanner. Scanners tell you about known vulnerabilities. GitGrit lets you check anything you decide matters, across every repository, and prove that a fix landed everywhere. It also runs the [AI tooling checks](ai-coding-standards.md) that most security tools don't cover, like blanket permissions in a committed `.claude/settings.json`.

## FAQ

### How fast can I check a new issue?
As fast as you can write a few lines of Python. Then run it across all repositories at once.

### Does it check every branch?
Yes. GitGrit records results per commit and per branch, and you choose which branches and events each standard runs on.

### Where does the check run?
In an isolated sandbox, on GitGrit's cloud or on your own infrastructure if you self-host.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20security%20fixes%20across%20repositories).
