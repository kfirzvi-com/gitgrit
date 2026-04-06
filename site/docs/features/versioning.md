# Policy Versioning

Every change to a policy is tracked as a version, giving you a full audit trail of who changed what and when.

## What's tracked

A version snapshot is created whenever a policy is:

- **Created** — v1
- **Edited** — v2, v3, ...
- **Installed from marketplace** — v1 with source noted
- **Updated from marketplace** — new version with source noted
- **Reverted** — new version referencing the reverted-to version

Each version stores: code, description, criteria, test cases, labels, the user who made the change, and a summary.

## Viewing history

On any policy detail page, scroll down to the **Version History** table. You'll see:

| Column | Description |
|--------|-------------|
| Version | Link to the version detail page |
| Change | What happened (Created, Updated, Reverted, etc.) |
| By | Email of the user who made the change |
| When | How long ago |

## Reverting

Click **Revert** on any older version to restore the policy to that state. This creates a *new* version (non-destructive) — your history is preserved.

## Version detail

Click a version number to see the full snapshot: code with syntax highlighting, labels, criteria, and all metadata at that point in time.
