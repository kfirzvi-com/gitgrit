#!/usr/bin/env bash
# PreToolUse hook — runs before every Edit or Write.
#
# Purpose: if a GitGrit project has been resolved this session AND has at least one active
# policy linked, remind the model to call validate_edit on the proposed change so the
# server can attribute introduced violations vs. pre-existing ones. Silent in every other
# case (no session file, no policies loaded, or pre-v2 session schema).
set -euo pipefail

ABS_GIT_DIR=$(git rev-parse --absolute-git-dir 2>/dev/null) || exit 0
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/gitgrit"
SESSION_HASH=$(printf '%s' "$ABS_GIT_DIR" | sha256sum | cut -c1-16)
SESSION_FILE="$CACHE_DIR/$SESSION_HASH.json"
[ -f "$SESSION_FILE" ] || exit 0

SESSION_FILE="$SESSION_FILE" python3 - <<'PYEOF'
import json, os, sys

try:
    with open(os.environ["SESSION_FILE"]) as f:
        data = json.load(f)
except Exception:
    sys.exit(0)

# Only emit the enforcement reminder when the session was bootstrapped under the v2
# schema AND policies are actually loaded for this project. Pre-v2 files predate the
# explicit policies_loaded flag and are treated as "not loaded" (the user will
# re-bootstrap on next session start).
if data.get("version", 1) < 2 or not data.get("policies_loaded"):
    sys.exit(0)

project_id = data.get("project_id") or ""
project_name = data.get("project_name") or "(unknown)"

context = (
    f"GitGrit enforcement is active for project: {project_name} (project_id={project_id}).\n"
    f"Before applying this Edit/Write, call gitgrit/validate_edit with:\n"
    f"  - project_id={project_id}\n"
    f"  - file_path: the target path of this Edit/Write (relative to repo root)\n"
    f"  - prior_content: the file's current content (use the Read tool to fetch it; pass null for new files)\n"
    f"  - new_content: the proposed content of the file after this edit\n"
    f"Block on `introduced_violations` — name the policy, quote the matched substring, propose a fix, "
    f"and wait for confirmation. Treat `pre_existing_violations_count` as informational only; "
    f"do not try to fix pre-existing violations unless the developer asks. Read `notes` for soft warnings."
)

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "additionalContext": context,
    }
}))
PYEOF
