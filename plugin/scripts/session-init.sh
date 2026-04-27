#!/usr/bin/env bash
# SessionStart hook — runs once per Claude Code session.
#
# Purpose: detect the current git repo, emit an additionalContext block that
# tells the model which GitGrit MCP tools to call and where to write session
# state. No network calls, no business logic — just git plumbing + a pointer
# to the server-side Policy Enforcement rule.
set -euo pipefail

emit() {
  # Safely emit a SessionStart additionalContext JSON, letting Python handle
  # all string escaping so server- or git-supplied values can't break the JSON.
  MESSAGE="$1" python3 - <<'PYEOF'
import json, os
print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": os.environ["MESSAGE"],
    }
}))
PYEOF
}

# Not a git repo — disable silently.
if ! git rev-parse --git-dir > /dev/null 2>&1; then
  emit "Not a git repository. GitGrit enforcement is disabled for this session."
  exit 0
fi

RAW_URL=$(git remote get-url origin 2>/dev/null || true)
if [ -z "$RAW_URL" ]; then
  emit "No 'origin' git remote found. GitGrit enforcement is disabled for this session."
  exit 0
fi

# Normalize into a browser-style web URL:
#   - strip embedded credentials:       https://user:tok@host/... -> https://host/...
#   - convert SSH form to HTTPS:        git@host:owner/repo(.git) -> https://host/owner/repo(.git)
#   - strip trailing .git:              ...repo.git               -> ...repo
# GitGrit stores projects with the credential-free HTTPS browser URL in Project.web_url,
# so sending the SSH form or a URL with .git would always miss the web_url fallback.
WEB_URL=$(printf '%s' "$RAW_URL" \
  | sed 's|https://[^@]*@|https://|' \
  | sed 's|^git@\([^:]*\):|https://\1/|' \
  | sed 's|\.git$||')

# Derive owner/repo full_path (everything after the host).
FULL_PATH=$(printf '%s' "$WEB_URL" | sed 's|^https\?://[^/]*/||')

# Session state lives under XDG cache, not inside the repo. Inside .git/ gets
# blocked by Claude Code's sensitive-file guard (the Write tool refuses even
# with bypassPermissions); at the repo root it would show up untracked in
# every user's clone. The cache path is keyed by the absolute .git dir so
# both hooks derive the same file without re-parsing the remote URL, and so
# two clones on disk don't share state.
ABS_GIT_DIR=$(git rev-parse --absolute-git-dir)
CACHE_DIR="${XDG_CACHE_HOME:-$HOME/.cache}/gitgrit"
SESSION_HASH=$(printf '%s' "$ABS_GIT_DIR" | sha256sum | cut -c1-16)
SESSION_FILE="$CACHE_DIR/$SESSION_HASH.json"

if ! mkdir -p "$CACHE_DIR" 2>/dev/null; then
  emit "Could not create GitGrit session cache at $CACHE_DIR. Enforcement disabled for this session."
  exit 0
fi

FULL_PATH="$FULL_PATH" WEB_URL="$WEB_URL" SESSION_FILE="$SESSION_FILE" \
  python3 - <<'PYEOF'
import json, os

full_path = os.environ["FULL_PATH"]
web_url = os.environ["WEB_URL"]
session_file = os.environ["SESSION_FILE"]

context = f"""GitGrit session bootstrap — repo detected: {full_path}

At the start of your next response, in this exact order:

1. Call gitgrit/session_bootstrap(repo_full_path="{full_path}", web_url="{web_url}"). The result has three keys: project, status, policies.

2. Branch on the result and tell the developer in one sentence, then write the session-state file:

   a. project.error == "no_match"
      → Tell the developer: "This repo isn't registered as a GitGrit project. Closest matches in your workspace: <project.candidates>. Enforcement is OFF for this session."
      → Write {session_file} with: {{"version": 2, "project_id": null, "project_name": null, "policies_loaded": false}}

   b. policies == []  (project resolved, but zero active policies linked)
      → Tell the developer: "Project <project.name> has no active policies linked in GitGrit. Enforcement is OFF for this session."
      → Write {session_file} with: {{"version": 2, "project_id": "<project.id>", "project_name": "<project.name>", "policies_loaded": false}}

   c. otherwise (project resolved + at least one policy)
      → Report status.grade in a single sentence (e.g. "Project <project.name>: grade <status.grade>.")
      → Write {session_file} with: {{"version": 2, "project_id": "<project.id>", "project_name": "<project.name>", "policies_loaded": true}}

   If the Write fails, mention it once and continue without enforcement. Do not retry.

3. From now on, follow the `policy-enforcement` skill for every Edit or Write in this session. That skill is the single source of truth for what to check and how to report violations; do not re-derive it.

HARD RULE — no invented enforcement:
You may only enforce a rule if its exact value appears in `policies[i].rules.forbidden_patterns` or `policies[i].rules.watched_files` for a policy returned in this session for *this* project. If a concern doesn't trace to one of those entries, do not raise it as a GitGrit violation. Filenames, READMEs, language idioms, marketplace policies, prior sessions, and your general knowledge are NOT sources of GitGrit rules. When in doubt, say "no GitGrit policy covers this" and continue.
"""

print(json.dumps({
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": context,
    }
}))
PYEOF
