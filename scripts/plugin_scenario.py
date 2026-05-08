"""Integration harness for the Claude Code plugin's MCP dependencies.

Exercises the exact MCP contract the plugin relies on (Layer 2 of the plugin
test plan), plus the seam between ``plugin/scripts/session-init.sh`` and the
server's ``resolve_project`` tool. Runs against a locally-seeded scenario.

Prereqs:
    1. `docker compose up -d` + `python manage.py migrate`
    2. `uvicorn gitgrit.asgi:application --port 8000` (in another shell)
    3. `eval "$(python manage.py seed_plugin_scenario)"` to seed and export
       MCP_TOKEN / TOKEN_PREFIX / FULL_PATH / WEB_URL / PROJECT_ID.

Usage:
    MCP_URL=http://localhost:8000/mcp MCP_TOKEN=$MCP_TOKEN \
        python scripts/plugin_scenario.py \
        --full-path "$FULL_PATH" --web-url "$WEB_URL" \
        --token-prefix "$TOKEN_PREFIX"

Exit codes: 0 = all assertions passed, 1 = one or more failed.
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

REPO_ROOT = Path(__file__).resolve().parents[1]
SESSION_INIT = REPO_ROOT / "plugin" / "scripts" / "session-init.sh"

_FULL_PATH_RE = re.compile(r'repo_full_path="([^"]+)"')
_WEB_URL_RE = re.compile(r'web_url="([^"]+)"')


class Results:
    def __init__(self) -> None:
        self.steps: list[tuple[str, bool, str]] = []

    def ok(self, name: str, detail: str = "") -> None:
        self.steps.append((name, True, detail))
        print(f"  [OK]   {name}" + (f" — {detail}" if detail else ""))

    def fail(self, name: str, detail: str) -> None:
        self.steps.append((name, False, detail))
        print(f"  [FAIL] {name} — {detail}")

    @property
    def all_passed(self) -> bool:
        return all(ok for _, ok, _ in self.steps)


def _extract_tool_result(call_result) -> object:
    """Return the structured payload from a CallToolResult.

    FastMCP wraps return values in ``structuredContent`` when available; falls
    back to parsing the first text content block as JSON.
    """
    structured = getattr(call_result, "structuredContent", None)
    if structured is not None:
        if isinstance(structured, dict) and set(structured.keys()) == {"result"}:
            return structured["result"]
        return structured
    for block in getattr(call_result, "content", []) or []:
        text = getattr(block, "text", None)
        if text is not None:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
    return None


def _seed_repo(origin: str) -> tuple[Path, tempfile.TemporaryDirectory]:
    tmpdir = tempfile.TemporaryDirectory()
    path = Path(tmpdir.name)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(
        ["git", "remote", "add", "origin", origin],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path, tmpdir


def _run_session_init(repo: Path) -> tuple[str, str]:
    """Invoke session-init.sh in ``repo``; return (full_path, web_url) from context."""
    result = subprocess.run(
        ["bash", str(SESSION_INIT)], cwd=repo, capture_output=True, text=True, check=True
    )
    payload = json.loads(result.stdout)
    ctx = payload["hookSpecificOutput"]["additionalContext"]
    m_fp = _FULL_PATH_RE.search(ctx)
    m_wu = _WEB_URL_RE.search(ctx)
    if not m_fp or not m_wu:
        raise RuntimeError(f"session-init.sh context missing fields: {ctx!r}")
    return m_fp.group(1), m_wu.group(1)


def _revoke_token(prefix: str) -> None:
    subprocess.run(
        ["uv", "run", "python", "manage.py", "revoke_api_token", "--prefix", prefix],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
    )


async def _mcp_session(url: str, token: str):
    return streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"})


async def run_scenarios(
    url: str, token: str, full_path: str, web_url: str, token_prefix: str
) -> Results:
    r = Results()

    # --- 1–3: happy path with the valid token ----------------------------
    print("Happy path (valid token, seeded project):")
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. resolve_project
            result = _extract_tool_result(
                await session.call_tool(
                    "resolve_project",
                    {"repo_full_path": full_path, "web_url": web_url},
                )
            )
            if isinstance(result, dict) and result.get("error"):
                r.fail("resolve_project matches seeded project", f"got {result}")
                return r
            if not isinstance(result, dict) or "id" not in result:
                r.fail("resolve_project matches seeded project", f"got {result!r}")
                return r
            project_id = result["id"]
            r.ok("resolve_project matches seeded project", f"matched_by={result.get('matched_by')}")

            # 2. get_project_status
            status = _extract_tool_result(
                await session.call_tool("get_project_status", {"project_id": project_id})
            )
            if not isinstance(status, dict) or "grade" not in status:
                r.fail("get_project_status returns grade", f"got {status!r}")
            else:
                r.ok("get_project_status returns grade", f"grade={status['grade']}")

            # 3. get_active_policies_for_project
            policies = _extract_tool_result(
                await session.call_tool(
                    "get_active_policies_for_project", {"project_id": project_id}
                )
            )
            if not isinstance(policies, list) or len(policies) == 0:
                r.fail(
                    "get_active_policies_for_project returns seeded policy",
                    f"got {policies!r}",
                )
            else:
                r.ok(
                    "get_active_policies_for_project returns seeded policy",
                    f"{len(policies)} policies",
                )

            # 4. no_match path
            miss = _extract_tool_result(
                await session.call_tool(
                    "resolve_project",
                    {"repo_full_path": "zzz-does-not-exist/zzz", "web_url": ""},
                )
            )
            if not (isinstance(miss, dict) and miss.get("error") == "no_match"):
                r.fail("resolve_project no_match returns candidates", f"got {miss!r}")
            elif not isinstance(miss.get("candidates"), list):
                r.fail(
                    "resolve_project no_match returns candidates",
                    f"candidates not a list: {miss!r}",
                )
            else:
                r.ok(
                    "resolve_project no_match returns candidates",
                    f"{len(miss['candidates'])} candidates",
                )

    # --- 5: wrong token → 401 --------------------------------------------
    print("Auth failure:")
    bad_token = "grit_invalid_token_does_not_exist_abc123"
    try:
        async with streamablehttp_client(
            url, headers={"Authorization": f"Bearer {bad_token}"}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool("resolve_project", {"repo_full_path": "x/y"})
        r.fail("invalid token is rejected", "session opened without error")
    except Exception as exc:
        r.ok("invalid token is rejected", type(exc).__name__)

    # --- 6: Layer-1↔2 round-trip -----------------------------------------
    print("Layer 1 -> Layer 2 round-trip (session-init.sh output -> resolve_project):")
    origins = [
        f"https://github.com/{full_path}.git",
        f"https://github.com/{full_path}",
        f"https://alice:secret@github.com/{full_path}.git",
        f"git@github.com:{full_path}.git",
        f"git@github.com:{full_path}",
    ]
    async with streamablehttp_client(
        url, headers={"Authorization": f"Bearer {token}"}
    ) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            for origin in origins:
                repo, keep_alive = _seed_repo(origin)
                try:
                    hp, wu = _run_session_init(repo)
                finally:
                    keep_alive.cleanup()
                result = _extract_tool_result(
                    await session.call_tool(
                        "resolve_project",
                        {"repo_full_path": hp, "web_url": wu},
                    )
                )
                if isinstance(result, dict) and "id" in result:
                    r.ok(f"round-trip: {origin!r}", f"full_path={hp}")
                else:
                    r.fail(
                        f"round-trip: {origin!r}",
                        f"hp={hp!r} wu={wu!r} resolve={result!r}",
                    )

    # --- 7: token revoked mid-flight --------------------------------------
    print("Token revocation:")
    _revoke_token(token_prefix)
    try:
        async with streamablehttp_client(
            url, headers={"Authorization": f"Bearer {token}"}
        ) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                await session.call_tool(
                    "resolve_project", {"repo_full_path": full_path}
                )
        r.fail("revoked token is rejected", "session accepted a revoked token")
    except Exception as exc:
        r.ok("revoked token is rejected", type(exc).__name__)

    return r


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-path", required=True)
    ap.add_argument("--web-url", required=True)
    ap.add_argument("--token-prefix", required=True)
    args = ap.parse_args()

    url = os.environ.get("MCP_URL")
    token = os.environ.get("MCP_TOKEN")
    if not url or not token:
        print("ERROR: MCP_URL and MCP_TOKEN env vars are required", file=sys.stderr)
        return 1

    print(f"MCP_URL={url}")
    print(f"full_path={args.full_path}  web_url={args.web_url}")
    print()

    try:
        results = asyncio.run(
            run_scenarios(url, token, args.full_path, args.web_url, args.token_prefix)
        )
    except Exception as exc:
        print(f"\nFATAL: scenario crashed: {exc}", file=sys.stderr)
        return 1

    print()
    passed = sum(1 for _, ok, _ in results.steps if ok)
    total = len(results.steps)
    print(f"{passed}/{total} assertions passed")
    return 0 if results.all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
