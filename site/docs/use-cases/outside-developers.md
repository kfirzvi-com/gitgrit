---
title: "Hold contractors and outside developers to your engineering standards"
description: "Contractors, outsourced teams and partners building on your platform write code you don't review line by line. GitGrit checks their repositories against your standards on every push."
---

<p class="gg-uc-page-eyebrow" markdown>:material-handshake-outline: Use case · Contractors, outsourced teams and platform partners</p>

# Hold outside developers to your standards

**The short answer:** more and more of your code is written by people outside your team: contractors, an outsourced team, partners who build on your platform or SDK. You can't review every line, and you can't sit next to them. GitGrit checks their repositories against your standards on every push, so you know the code meets your bar before it reaches you.

## The problem

Outside developers are good at what they do, but they don't share your habits, your wiki or your Slack:

- An outsourced team delivers a service that works, but has no CI, no lockfile and no owner.
- A contractor leaves, and nobody knows whether their repository followed your conventions.
- Partners building on your platform are supposed to include your SDK and follow your integration rules, and you only find out they didn't when something fails in production.

Code review helps for what you see. It doesn't help for repositories you never open.

## How GitGrit helps

### The same standards for everyone

Connect the repositories outside teams work in, and they're checked against the same standards as your own, on every push, pull request and tag.

### Clear requirements, checked automatically

Mark the rules that matter as **Required**. When something fails, the result shows exactly what's missing and why, without waiting for your review.

### Your own rules, as code

Every standard is a short piece of Python, so you can check rules that are specific to you: that every app includes your SDK, uses a supported version of it, or has the configuration your platform expects.

### One view across your team and theirs

See every repository's grade in [one screen](engineering-visibility.md), yours and theirs, and know which deliveries are ready to accept.

## Example: a platform with outside game developers

One of our design partners runs a gaming platform. Every game must include specific SDK code, but the games are built by outside developers. Together we chose the standards their platform needs, and GitGrit checks every game's repository against them.

## FAQ

### Do outside developers need a GitGrit account?
No. GitGrit checks the repositories you connect. You can show each repository's grade with a [badge](../features/badges.md) in its README, or add `gitgrit check --wait` from the [CLI](../getting-started/cli.md) to their CI, so a failing grade fails the build.

### What access does GitGrit need?
A GitHub App or GitLab connection with the access you choose. GitGrit is open source (MIT), so you can read every line, and it can run self-hosted on your own infrastructure.

### Can I accept a delivery based on the grade?
Many teams use a passing grade, or no failing Required standards, as part of the bar for accepting work.

## Talk to us

We'd love to hear how you work with outside teams, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20outside%20developers).
