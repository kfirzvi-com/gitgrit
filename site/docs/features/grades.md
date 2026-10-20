# Grades

Every project has a grade: one letter from **A+** to **F**, with a one-line reason. The grade is on the project page, the badge, the dashboard, the stack pages, the `gitgrit health` command and the REST API (`/status/` and `/health/`; each commit in `/commits/` carries its own letter).

## Where the letter comes from

The grade is the pass rate of the standards attached to the project, using each standard's own verdict: the `passed` value its script returns. A standard's 0–100 score is still shown per run but no longer aggregates into the grade.

| Letter | Pass rate |
|---|---|
| **A+** | every standard passed |
| **A** | 90% or more |
| **B** | 75% or more |
| **C** | 60% or more |
| **D** | below 60% |
| **F** | a critical standard is failing or could not be verified (see below) |

A standard counts toward the grade only when:

- it is attached to the project, enabled and not a draft;
- its latest finished run read the standard's **home branch**. That is the project's default branch, unless the standard's Branch/Tag Filter names one branch literally (`^develop$`): then it is that branch. Runs on any other branch, a feature-branch push or a pull request, show in the project's activity but never move the grade: a half-finished branch must not fail the project, and a fix that only exists on a branch must not pass it before it merges. The newest commit on the home branch wins, so checking an old commit again does not change the picture;
- GitGrit itself did not fail the run. A job failure, a sandbox error or a worker restart keeps the previous result; a GitGrit outage never changes a grade.

A standard that errors inside its own code counts as not passed: an error in a script you wrote is yours to fix.

A standard with no counting run yet on its home branch is listed on the project page as *not evaluated* and neither passes nor fails. A project with nothing evaluated has no grade, shown as **—**.

## The gate: critical standards

In the project's standards table each attached standard has a **level**:

| Level | What it does |
|---|---|
| **High** (default) | counts toward the pass rate |
| **Critical** | gates the grade: a failing or unverified result makes the project an F |

Set it per row in the **Level** column, or for every listed row at once with **Set level: High** / **Set level: Critical**; the Filter and the `level:critical` search show one level. The level lives on the link between the project and the standard, so the same standard can gate one project and not another. Every attachment starts at High; detaching and reattaching resets it. The API's `top_offenders` carry each standard's `level`.

A critical standard that fails makes the project an **F**, whatever the other standards say. The reason names it: `F — No secrets failing`.

### F — could not verify

A critical standard whose own run errors also makes the project an **F**, with the reason `could not verify No secrets`. GitGrit could not confirm the thing you said must hold, so it does not pretend it does. The workspace gets a *could not verify* notice when this starts; a repeat error is silent, and the next error after a pass notifies again.

### Each commit has a letter too

The project page's history and the API's `/commits/` list grade every checked commit by the same rule over the standards that ran on it, each read at the level it ran under. A standard set to Critical later does not rewrite an old commit's verdict, and one detached later still explains it.

## Neglect caps

A standard left failing is worse than one that just broke. Each attachment keeps a clock: it starts the first time the standard fails on its home branch and runs until the standard passes there again.

| Failing for | The grade is capped at |
|---|---|
| more than 14 days | **B** |
| more than 30 days | **C** |

The cap lowers the letter, never raises it: a project that is already a D stays a D. It never applies behind the gate: a failing critical standard is an F whatever the clocks say. The reason names the standard and the days, for example `B — Old README failing for 18 days`.

How the clock behaves:

- it starts at the first failure on the **home branch**; runs on other branches never start or stop it;
- a pass resets it, so the next failure starts a fresh clock;
- an error inside the standard's own run keeps it running: an errored day is a failing day;
- a GitGrit failure (job error, sandbox error, worker restart) does not touch it;
- detaching the standard deletes the clock; reattaching starts with none.

On the day neglect caps shipped, every attachment that was already failing had its clock started then, not at its old failure, so no project was capped by the release alone.

A commit's letter has no clock: a commit verdict is never capped.

## Workspace and stack grades

The dashboard shows the workspace grade and each stack page shows the stack grade. Both are the **worst** project grade among their projects: one F project is an F stack. Projects with no grade are ignored, so an empty project never drags a stack down.

Health colours on the architecture map, the badge and the API's `level` follow the letter: **F** is `failing` (red), **C** and **D** need `attention` (amber), **A+**, **A** and **B** are `good` (green), and no grade is `unknown` (grey).

## The reason line

The reason says why the grade is not one higher, in this order:

1. a critical standard failing or unverified;
2. a neglect cap holding the letter down, for example `Old README failing for 18 days`;
3. how many standards are failing, for example `2 standards failing`;
4. `perfect`, when everything passed.

## Breaking change in this release

The API's `level` values were renamed: `healthy`, `warning` and `critical` are now `good`, `attention` and `failing` (and `unknown` when there is no grade). If you compare `level` in a script or a dashboard, update the values. On `top_offenders`, the boolean `critical` is replaced by `level` (`high` or `critical`): read `level == "critical"` where you read `critical`. `grade` and `reason` are new fields on `/health/` and on each commit.

## Release-day note

Grades replaced the compliance percentage. On the day of the change some projects move to a different band, because every move is toward the truer number:

- runs that errored because of GitGrit itself no longer count as 0;
- partial scores no longer aggregate: a standard either passed or did not;
- disabled and draft standards drop out.

Every attachment starts at High, so no project becomes an F by the change alone. Set the standards that must hold to Critical in the project's standards table to turn the gate on.
