---
title: "Roll out a new engineering standard across every repository"
description: "Introduce a new engineering standard or migration across dozens of repositories and track it to done. GitGrit lets you dry-run the change, roll it out everywhere at once, and watch every repository catch up."
---

<p class="gg-uc-page-eyebrow" markdown>:material-rocket-launch-outline: Use case · Rolling out new standards and migrations</p>

# Roll out a change across every repository

**The short answer:** deciding on a new standard takes one meeting. Getting it into every repository takes months of reminders and spreadsheets. With GitGrit you write the standard once, dry-run it to see who it affects, roll it out to every repository at once, and watch the list of repositories that still need the change shrink to zero.

## The problem

You decided something should change everywhere:

- Every service moves to the new CI setup.
- Every repository needs a CODEOWNERS file.
- Every Dockerfile pins its base image.
- A new team convention, or a migration off an old library.

Then comes the hard part. Someone opens a ticket per team, keeps a spreadsheet, and asks for status every week. Half the repositories are done, nobody knows which half, and the migration stalls at 80%.

## How GitGrit helps

### Write the rule once

Turn the decision into a standard: a short, readable piece of code. Use a ready-made one from the marketplace, or [write your own](../getting-started/standards.md).

### Dry-run before you roll out

Test the new standard in the sandbox first, so you know it does what you meant before it reaches anyone's grade.

### Start gentle, then raise the bar

Attach it as **Minor** so teams see it without pressure, then move it to **Major** or **Required** when the deadline arrives. You choose the importance per project.

### Track it to done

The dashboard shows exactly which repositories pass and which don't. No spreadsheet, no status meetings, and you can see the moment the last repository catches up.

### It stays done

The standard keeps running on every push. A new repository that skips the change, or an old one that drifts back, is flagged right away.

### Every change on record

Standards are [versioned](../features/versioning.md), so you can see how a rule evolved and revert it in one click.

## FAQ

### How is this different from opening a ticket per team?
Tickets track whether someone said they did it. GitGrit checks the repository itself, on every push, so the status is always true.

### Can a standard apply to only some repositories?
Yes. You choose which projects, branches and events each standard applies to.

### Can it check a migration away from a library?
Yes. Any rule you can check by reading the repository, like "no imports of the old library", can be written as a standard.

## Talk to us

We'd love to hear what you're rolling out next, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20rolling%20out%20standards).
