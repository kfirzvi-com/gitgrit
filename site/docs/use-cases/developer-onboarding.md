---
title: "Developer onboarding: engineering standards from day one"
description: "Help new developers follow your team's engineering standards from their first commit. GitGrit turns \"how we do things here\" into checks that run on every repository, so every new repo starts on the golden path."
---

<p class="gg-uc-page-eyebrow" markdown>:material-account-plus-outline: Use case · Developer onboarding</p>

# Onboard new developers onto your standards

**The short answer:** every new developer brings their own habits, and "how we do things here" is usually in a wiki nobody reads. GitGrit turns it into checks that run on every push, so new developers learn your standards from their first commit, and every new repository starts on the golden path.

## The problem

Your team is growing. Each new developer is good, and each one learned a different way to build. Today they learn yours from:

- An onboarding doc written two years ago
- Review comments on their first pull requests
- A senior engineer who answers the same questions every month

It works, slowly, and it depends on the people who already know.

## How GitGrit helps

### Standards that explain themselves

Each GitGrit standard is a short, readable rule with a clear description. When a check fails, the developer sees exactly what's missing and why it matters, on their own commit, without waiting for a reviewer.

### Every new repository on the golden path

Ready-made packs and standards from the marketplace cover the basics a new repository should have from day one:

- A README, a contributing guide and a changelog
- A CODEOWNERS file, so reviews go to the right people
- A CI pipeline and a configured linter
- A dependency lockfile and a supported Node.js or Python version

Connect a new repository and it's graded against the same standards as the rest.

### Reviews about the code, not the checklist

When the basics are checked automatically, reviewers stop repeating them and spend their time on the design and the logic.

### Same standards for new AI tools

A new AI assistant is a new team member too. GitGrit checks that every repository has [current, concise agent instructions](ai-coding-standards.md), so the assistant learns the same standards.

## FAQ

### Does this replace onboarding docs?
No. It makes the rules in them true. The doc explains why; GitGrit checks that it happens.

### Can we use our own standards?
Yes. Start from ready-made packs, then [write your own](../getting-started/standards.md) in a few lines of Python.

### How long does setup take?
Connect a repository from GitHub or GitLab, install a pack, and you'll see a grade within minutes.

## Talk to us

We'd love to hear how your team is growing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20developer%20onboarding).
