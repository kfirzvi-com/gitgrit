---
title: "AI coding standards: check CLAUDE.md, AGENTS.md and AI-written code"
description: "Keep AI-written code on your engineering standards. GitGrit checks every change, human or AI, on every push, keeps CLAUDE.md, AGENTS.md and Cursor rules current and safe, and keeps AI spend on budget."
---

<p class="gg-uc-page-eyebrow" markdown>:material-robot-outline: Use case · AI coding standards</p>

# Keep AI-written code on your standards

**The short answer:** rule files like `CLAUDE.md`, `AGENTS.md` and `.cursorrules` tell an AI assistant what to do while it writes. Nothing checks what actually landed, or whether those files are still true. GitGrit does both: it checks every change, human or AI, against the same standards on every push, and it checks the agent files themselves.

## The problem

You rolled AI coding tools out to every team. Code ships faster than ever. But:

- Some repositories have a `CLAUDE.md`, some don't, and some have one that describes the codebase as it was six months ago.
- A stale instruction file is worse than none. It confidently tells the assistant to use scripts that were removed and conventions you dropped.
- Someone added `Bash(*)` to `.claude/settings.json` "just for now", and every tool call now runs without asking.
- A committed `.mcp.json` points at `localhost`, so it works on one laptop and silently breaks for everyone else.

None of this shows up in code review. It shows up later, as code that doesn't match how your team builds.

## How GitGrit helps

### Every change is checked, whoever wrote it

GitGrit runs your standards on every push, pull request and tag, on every branch. An AI agent's commit gets the same checks as anyone else's, and the same grade. AI review tools suggest; GitGrit verifies.

### Agent files are standards too

The ready-made **Agentic Standards** pack installs in one click:

| Standard | What it checks |
|---|---|
| Agent Instructions Present | The repository has at least one agent file: `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules` or `.github/copilot-instructions.md` |
| Agent Instructions Not Stale | The agent file was updated within 30 days of the repository's last update |
| Agent Instructions Size Bounded | The agent file stays under 200 lines, so it fits the agent's context and stays readable |
| Claude Settings — No Blanket Allow Rules | A committed `.claude/settings.json` doesn't allow `Bash(*)`, `Bash(sudo:*)`, `Bash(rm:*)` or `*` |
| MCP Config Is Portable | A committed `.mcp.json` is valid JSON and doesn't point at `localhost` |

### Keep AI spend in check

Some standards need judgment, like "does this `CLAUDE.md` actually describe this repository?", so they use an AI model, with your own provider and key. GitGrit shows exactly what that costs:

- **Tokens per provider and model**, input and output apart, and what they were spent on
- **Which standards use far more** than the others, so you know where to look
- **Budgets per model**, per day, week or month, with a warning when one runs low and the option to hold back runs once it's used up

The dashboard shows each budget as a fuel gauge, with a low-fuel light when one needs you. Nothing spends on AI until you've set a budget.

### Your agents can read the standards

The [`gitgrit` CLI](../getting-started/cli.md) and public API give agents the same view you have, so an agent can check where a repository stands before it opens a pull request.

## CLAUDE.md best practices you can check automatically

Most `CLAUDE.md` advice comes down to a few rules. Each one is a GitGrit standard you can turn on:

1. **Have one.** Every active repository has an agent instruction file.
2. **Keep it current.** Update it when the code changes, not once a year.
3. **Keep it short.** Under 200 lines, about the repository, not a general style guide.
4. **Don't hand out blanket permissions.** No `Bash(*)` in committed settings.
5. **Keep shared config portable.** No `localhost` in a committed `.mcp.json`.

Need a rule that isn't on the list? Every standard is a short piece of Python, so you can [write your own](../getting-started/standards.md), or use an LLM check when a rule needs judgment, like "does this `CLAUDE.md` actually describe this repository?"

## FAQ

### Doesn't the AI already follow our CLAUDE.md?
It follows it while it writes, if the file is there and correct. GitGrit checks what landed in the repository afterwards, across every repository, and tells you when the file itself has drifted.

### Does this replace AI code review?
No. AI reviewers comment on one pull request at a time. GitGrit checks every repository against your standards all the time, including repositories nobody is changing.

### Does GitGrit track my team's AI coding tool spend?
No. The usage and budgets cover the AI models GitGrit's own checks use. Your team's coding assistants are billed by their own providers.

### Which AI tools does it cover?
The agent-file standards look for `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `.cursorrules` and `.github/copilot-instructions.md`. The code checks apply to all code, whoever or whatever wrote it.

## Talk to us

We'd love to hear how your team works with AI, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%20for%20AI-written%20code).
