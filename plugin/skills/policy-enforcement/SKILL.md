---
name: policy-enforcement
description: Apply GitGrit policy enforcement before writing or editing code in a repository that has been resolved via gitgrit/session_bootstrap. Use when active policies are loaded and the next action is an Edit or Write; skip entirely if no policies are loaded for the project.
---

# Policy enforcement

GitGrit's policy engine runs server-side. The `validate_edit` MCP tool diffs the proposed
edit against the file's prior content and returns only the violations this edit introduced;
pre-existing violations are reported as a count only and never block.

## Before every Edit or Write

1. **If `policies_loaded` is false** (no project match, or zero active policies linked) — do
   nothing. Say so once and stop. Do not raise GitGrit-flavored verdicts when no policies are
   loaded.

2. **Otherwise call `gitgrit/validate_edit`** with:
   - `project_id` — read from the session-state file (`project_id` field).
   - `file_path` — the target path of the Edit/Write, relative to the repo root.
   - `prior_content` — the file's current content. Use the Read tool to fetch it. Pass
     `null` for new files.
   - `new_content` — the proposed content after the edit.

3. **Branch on the response:**
   - `introduced_violations` is a list. For each entry, name the policy, quote the
     `matched_substring`, propose a concrete fix, and wait for developer confirmation. If
     the developer says proceed anyway, proceed — the developer has final say.
   - `pre_existing_violations_count` is informational. Do not try to fix pre-existing
     violations unless the developer asks.
   - `notes` is a list of soft warnings (e.g. extractor couldn't fully parse a rule;
     server-side sandbox is authoritative on the next webhook event). Surface these
     verbatim — don't paraphrase.

## Hard rule — no invented enforcement

Only enforce a rule that came back from `validate_edit` for *this* project. Filenames,
READMEs, language idioms, prior sessions, marketplace policies, and your general knowledge
are not sources of GitGrit rules. When in doubt, say "no GitGrit policy covers this" and
continue.
