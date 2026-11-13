---
title: "Find repositories on end-of-life Node.js and Python versions"
description: "Node.js 20 reached end of life in April 2026 and Python 3.10 in October 2026. GitGrit checks every repository on every push and shows which ones still run an end-of-life version."
---

<p class="gg-uc-page-eyebrow" markdown>:material-clock-alert-outline: Use case · Node.js and Python end of life</p>

# Find repositories on end-of-life runtimes

**The short answer:** Node.js 20 reached end of life on April 30, 2026, and Python 3.10 in October 2026. End-of-life versions get no more security fixes, and libraries start dropping support. GitGrit checks every repository on every push and shows which ones still run an end-of-life version, so you can plan the upgrade instead of being forced into it.

## The problem

Runtime versions are invisible debt. Each repository pins its own version in its own file, and nobody looks across all of them. You usually find out when:

- A dependency update needs a newer runtime
- A security review asks which services are on supported versions
- A platform drops an old version and a deploy fails

By then several repositories need the same migration at once.

## How GitGrit helps

Two ready-made standards check the version each repository declares:

| Standard | Where it looks |
|---|---|
| Node.js Version Not EOL | `.nvmrc`, `.node-version`, the `engines` field in `package.json`, `.tool-versions` |
| Python Version Not EOL | `.python-version`, `requires-python` in `pyproject.toml`, `runtime.txt`, `.tool-versions` |

They come with the **Node.js Standards** and **Python Standards** packs, next to checks that dependencies are locked and, for Python, that a version is pinned at all.

### Every repository, one view

Each repository's grade shows the result, so you can see at a glance which repositories still need the upgrade, and watch the list shrink.

### Caught on the push

A new repository that starts on an old version, or a change that pins one, is flagged on that push.

### Plan ahead

Because standards are code, you can tighten the rule before the deadline. For example, write a [standard of your own](../getting-started/standards.md) that warns six months before a version reaches end of life, and mark it Minor so it informs without failing anything.

## Node.js and Python end-of-life dates

| Runtime | Version | End of life |
|---|---|---|
| Node.js | 18 | April 30, 2025 |
| Node.js | 20 | April 30, 2026 |
| Node.js | 22 | April 30, 2027 |
| Python | 3.9 | October 2025 |
| Python | 3.10 | October 2026 |
| Python | 3.11 | October 2027 |

Sources: [Node.js release schedule](https://github.com/nodejs/release#release-schedule) · [Python versions](https://devguide.python.org/versions/)

## FAQ

### Is this a security scanner?
No. It checks which runtime version each repository declares, so you can keep your stack current. It doesn't scan for vulnerabilities.

### What if a repository doesn't declare a version?
The Python Standards pack includes a standard that checks a version is specified, so the gap shows up too. For Node.js, you can add the same check as a standard of your own.

### Can I check other runtimes?
Yes. Every standard is a short piece of Python, so you can write the same check for Go, Java or anything else your repositories declare.

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20end-of-life%20runtimes).
