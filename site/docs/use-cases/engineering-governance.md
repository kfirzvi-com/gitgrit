---
title: "Engineering governance with policy as code"
description: "Keep your engineering standards in one place as versioned code. Decide which repositories, branches and events each applies to, and how much it matters."
---

<p class="gg-uc-page-eyebrow" markdown>:material-tune-variant: Use case · Engineering governance</p>

# Engineering governance: decide which standards apply where

Engineering governance is how you decide the rules your teams build by, and who they apply to. In most growing companies those rules live in a wiki, so there is **no lever to pull**. GitGrit turns them into **policy as code**: one place for every standard, a choice of **which repositories, branches and events** each one applies to, and **how much it matters**, with every change versioned.
{ .gg-uc-lead }

## The problem

You know how your company should build. But:

- The standards live in a **wiki or a Notion page**, and nobody can tell which of them are actually followed.
- **One rule for everything** doesn't fit: your payments service and an internal script shouldn't be held to the same bar.
- Changing a rule means a message in Slack and **hoping everyone saw it**.
- When someone asks "since when do we require this, and who decided?", **nobody knows**.

Governance that only exists on paper isn't governance. It's a suggestion.

## How GitGrit gives you control

### Your standards, in one place, as code

Every standard is a **short, readable Python function** that checks the repository and returns pass or fail with a reason. Start from [ready-made packs in the marketplace](../features/marketplace.md), adapt them, or [write your own](../getting-started/standards.md).

```python
def evaluate(project):
    files = project.list_files()
    if "CODEOWNERS" in files or ".github/CODEOWNERS" in files:
        return {"passed": True, "score": 100, "message": "CODEOWNERS found", "details": {}}
    return {"passed": False, "score": 0, "message": "No CODEOWNERS file", "details": {}}
```

### What runs where

Choose which standards apply to **each project**, on which **branches** and **events**: every push, pull requests only, tags, or only the main branch. A standard can also run only for projects in a given **language**.

### How much each one matters

Mark each standard **Required**, **Major** or **Minor**, per project. A failing Required standard fails the project. The rest count toward its grade. The same standard can be **Required for your core services** and **Minor for an internal tool**.

### Every change on record

Standards are [versioned](../features/versioning.md): **who changed what, when**, and a one-click revert. That's your audit trail for how the rules evolved.

### Rules that run the same way every time

Each check runs **in an isolated sandbox** against the repository itself and gets **the same answer every time**. Where a rule needs judgment, a standard can ask an AI model, but that's your choice, not the only option.

## Governance that doesn't slow teams down

Good engineering governance is **invisible until it matters**. There are no approval meetings and no checklists. Developers see the result on their own commits, and you only hear about it when a Required standard fails.

## FAQ

### What is engineering governance?
Engineering governance is the set of rules an engineering organization builds by, plus the means to apply and check them. GitGrit makes those rules executable: each one is code that runs on every repository it applies to.

### What does "policy as code" mean here?
Each engineering policy is a small program, not a sentence in a document. It runs on every push and gives a clear pass or fail with a reason, so the policy and what actually happens can't drift apart.

### Is GitGrit a compliance or GRC tool?
No. GitGrit governs **how your code is built**: repository setup, CI, dependencies, runtimes, agent files. It doesn't manage SOC 2 controls or vendor questionnaires.

### Can different teams have different standards?
Yes. You choose the standards and their importance per project, and you can group projects into stacks.

### Do I have to write code to use it?
No. Most teams start with ready-made packs and write their own standards later.

## Related

- [Engineering visibility: know where every repository stands](engineering-visibility.md)
- [Enforce engineering standards on every commit](enforce-engineering-standards.md)

## Talk to us

We'd love to hear what you're facing, and see together if we can help. [Let's talk](mailto:kfir@praktical.dev?subject=GitGrit%3A%20engineering%20governance).
