#!/usr/bin/env bash
# Build a throwaway "client repo" that looks like a real customer project.
#
# Layer 3 of the plugin test plan: Claude Code's SessionStart hook is gated on
# `git remote get-url origin`, so Layer 4 needs a real git repo on disk whose
# origin URL matches the full_path seeded by `seed_plugin_scenario`. This script
# produces that, plus a file that deliberately violates the seeded "No TODOs
# in source" policy and a control file that doesn't.
#
# Usage:
#   scripts/make_client_repo.sh <target-dir> <full_path>
#
# Example:
#   scripts/make_client_repo.sh /tmp/gitgrit-client-repo acme/backend
set -euo pipefail

TARGET="${1:?target-dir required}"
FULL_PATH="${2:?full_path required (e.g. acme/backend)}"

if [ -e "$TARGET" ]; then
  echo "refusing to overwrite existing path: $TARGET" >&2
  exit 1
fi

mkdir -p "$TARGET"
cd "$TARGET"

git init -q
git config user.email "plugin-test@example.com"
git config user.name  "plugin-test"

cat > main.py <<'PY'
# Entry point.
#
# TODO: refactor this file. The policy "No TODOs in source" forbids this marker.
def main():
    print("hello from main")


if __name__ == "__main__":
    main()
PY

cat > clean.py <<'PY'
"""A control file with no policy violations."""


def greet(name: str) -> str:
    return f"hello, {name}"
PY

cat > README.md <<MD
# $FULL_PATH

Throwaway client repo for GitGrit Claude Code plugin tests.

- main.py contains a TODO marker and should be flagged by the seeded policy.
- clean.py has no violations.
MD

git add -A
git commit -q -m "initial commit"
git remote add origin "https://github.com/${FULL_PATH}.git"

echo "client repo ready at $TARGET"
echo "  origin: $(git remote get-url origin)"
echo "  files:  $(ls)"
