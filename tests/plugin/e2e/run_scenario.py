"""Layer 4 behavioral test harness for the GitGrit Claude Code plugin.

Drives `claude -p --output-format stream-json --include-hook-events` in seeded
client repos and splits verdicts into two classes per the project's testing
convention:

  - Mechanical:  deterministic, expected 100% pass rate. Things the harness
                 controls (hook fired, expected tool_use appeared, exit 0).
  - Behavioral:  probabilistic, sampled. Things the model decides given its
                 context (did it flag the violation, did it report the grade,
                 did it surface the auth failure).

Each scenario is run ``--runs N`` times (default 3). Per-scenario JSON logs
are written to tests/plugin/e2e/results/ so regressions are comparable over
time.

Prereqs:
  1. docker compose up -d  (or an existing postgres on :5432)
  2. DB_NAME=gitgrit_plugin_test uv run python manage.py migrate
  3. DB_NAME=gitgrit_plugin_test uv run uvicorn gitgrit.asgi:application --port 8000

Usage:
  uv run python tests/plugin/e2e/run_scenario.py                     # all scenarios, N=3
  uv run python tests/plugin/e2e/run_scenario.py --runs 1            # smoke
  uv run python tests/plugin/e2e/run_scenario.py --scenario bootstrap
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = REPO_ROOT / "plugin"
MAKE_CLIENT_REPO = REPO_ROOT / "scripts" / "make_client_repo.sh"
RESULTS_DIR = REPO_ROOT / "tests" / "plugin" / "e2e" / "results"

SCRATCH_ROOT = Path("/tmp/gitgrit-e2e")
XDG_CACHE = SCRATCH_ROOT / "xdg-cache"
REPO_NORMAL = SCRATCH_ROOT / "repo-normal"
REPO_NOMATCH = SCRATCH_ROOT / "repo-nomatch"
REPO_NOGIT = SCRATCH_ROOT / "repo-no-git"

MCP_URL_DEFAULT = "http://localhost:8000/mcp"
DB_NAME = "gitgrit_plugin_test"
PER_RUN_BUDGET = "0.60"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class Assertion:
    name: str
    kind: str  # "mechanical" | "behavioral"
    passed: bool
    detail: str = ""


@dataclass
class RunResult:
    run_index: int
    exit_code: int
    duration_ms: int | None
    cost_usd: float | None
    num_turns: int | None
    result_text: str
    assertions: list[Assertion] = field(default_factory=list)
    events_path: str = ""

    def passed(self, kind: str) -> bool:
        rs = [a for a in self.assertions if a.kind == kind]
        return bool(rs) and all(a.passed for a in rs)


@dataclass
class ScenarioSpec:
    name: str
    description: str
    prompt: str
    build: Callable[["Context"], None]       # prepares repo, seeds, etc.
    mechanical: Callable[["Context", list[dict]], list[Assertion]]
    behavioral: Callable[["Context", list[dict]], list[Assertion]]
    behavioral_threshold: float = 0.80
    runs: int | None = None  # override the default --runs
    seed_args: list[str] = field(default_factory=list)  # extra args for `seed_plugin_scenario`


@dataclass
class Context:
    """Mutable state a scenario's build step fills in for assertions to read."""
    scenario: ScenarioSpec
    repo: Path = REPO_NORMAL
    token: str = ""
    token_prefix: str = ""
    full_path: str = ""
    web_url: str = ""
    project_id: str = ""
    expected_project_name: str = ""


# ---------------------------------------------------------------------------
# Infrastructure helpers
# ---------------------------------------------------------------------------

def _run(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
         check: bool = True, timeout: int | None = None) -> subprocess.CompletedProcess:
    merged = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd, cwd=(str(cwd) if cwd else None), env=merged,
        capture_output=True, text=True, check=check, timeout=timeout,
    )


def _seed(extra_args: list[str] | None = None) -> dict:
    cmd = ["uv", "run", "python", "manage.py", "seed_plugin_scenario"]
    if extra_args:
        cmd.extend(extra_args)
    out = _run(cmd, cwd=REPO_ROOT, env={"DB_NAME": DB_NAME}).stdout.strip()
    return dict(line.split("=", 1) for line in out.splitlines() if "=" in line)


def _revoke(prefix: str) -> None:
    _run(
        ["uv", "run", "python", "manage.py", "revoke_api_token", "--prefix", prefix],
        cwd=REPO_ROOT, env={"DB_NAME": DB_NAME},
    )


def _reset_scratch() -> None:
    if SCRATCH_ROOT.exists():
        shutil.rmtree(SCRATCH_ROOT)
    SCRATCH_ROOT.mkdir(parents=True)
    XDG_CACHE.mkdir(parents=True)


def _build_normal_repo(ctx: Context) -> None:
    if REPO_NORMAL.exists():
        shutil.rmtree(REPO_NORMAL)
    _run(["bash", str(MAKE_CLIENT_REPO), str(REPO_NORMAL), ctx.full_path], check=True)
    ctx.repo = REPO_NORMAL


def _build_nomatch_repo(ctx: Context) -> None:
    if REPO_NOMATCH.exists():
        shutil.rmtree(REPO_NOMATCH)
    _run(["bash", str(MAKE_CLIENT_REPO), str(REPO_NOMATCH), "definitely-not-seeded-xyz/nomatch"], check=True)
    ctx.repo = REPO_NOMATCH


def _build_no_git(ctx: Context) -> None:
    if REPO_NOGIT.exists():
        shutil.rmtree(REPO_NOGIT)
    REPO_NOGIT.mkdir(parents=True)
    (REPO_NOGIT / "README.md").write_text("# no git, just a dir\n")
    ctx.repo = REPO_NOGIT


def _session_file_for(repo: Path) -> Path:
    abs_git_dir = _run(["git", "rev-parse", "--absolute-git-dir"], cwd=repo).stdout.strip()
    digest = hashlib.sha256(abs_git_dir.encode()).hexdigest()[:16]
    return XDG_CACHE / "gitgrit" / f"{digest}.json"


def _clean_cache_for_repo(repo: Path) -> None:
    sf = _session_file_for(repo)
    if sf.exists():
        sf.unlink()


def _prepopulate_session_file(repo: Path, project_id: str, project_name: str) -> None:
    sf = _session_file_for(repo)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(json.dumps({
        "version": 2,
        "project_id": project_id,
        "project_name": project_name,
        "policies_loaded": True,
    }))


def _wait_for_mcp(url: str, timeout_s: int = 10) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except urllib.error.HTTPError:
            return True  # any HTTP response = server up
        except Exception:
            time.sleep(0.5)
    return False


def _invoke_claude(prompt: str, repo: Path, token: str, events_path: Path,
                   mcp_url: str) -> subprocess.CompletedProcess:
    mcp_config = json.dumps({
        "mcpServers": {
            "gitgrit": {
                "type": "http",
                "url": mcp_url,
                "headers": {"Authorization": f"Bearer {token}"},
            }
        }
    })
    env = {"XDG_CACHE_HOME": str(XDG_CACHE)}
    with events_path.open("w") as fp:
        return subprocess.run(
            [
                "claude", "-p", prompt,
                "--plugin-dir", str(PLUGIN_DIR),
                "--mcp-config", mcp_config,
                "--strict-mcp-config",
                "--output-format", "stream-json",
                "--include-hook-events",
                "--verbose",
                "--permission-mode", "bypassPermissions",
                "--max-budget-usd", PER_RUN_BUDGET,
            ],
            cwd=str(repo),
            stdout=fp,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ, **env},
            timeout=300,
        )


# ---------------------------------------------------------------------------
# Event-stream accessors
# ---------------------------------------------------------------------------

def load_events(path: Path) -> list[dict]:
    out = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def hook_response(events: list[dict], hook_name_prefix: str) -> dict | None:
    for e in events:
        if e.get("type") == "system" and e.get("subtype") == "hook_response":
            if (e.get("hook_name") or "").startswith(hook_name_prefix):
                return e
    return None


def hook_additional_context(events: list[dict], hook_name_prefix: str) -> str:
    h = hook_response(events, hook_name_prefix)
    if not h:
        return ""
    try:
        return json.loads(h.get("output", "{}")).get("hookSpecificOutput", {}).get("additionalContext", "") or ""
    except json.JSONDecodeError:
        return ""


def tool_uses(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        if e.get("type") == "assistant":
            for b in e.get("message", {}).get("content") or []:
                if b.get("type") == "tool_use":
                    out.append(b)
    return out


def tool_results(events: list[dict]) -> list[dict]:
    out = []
    for e in events:
        if e.get("type") == "user":
            for b in e.get("message", {}).get("content") or []:
                if b.get("type") == "tool_result":
                    out.append(b)
    return out


def tool_result_text(block: dict) -> str:
    c = block.get("content", "")
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return str(c)


def final_result(events: list[dict]) -> dict:
    for e in reversed(events):
        if e.get("type") == "result":
            return e
    return {}


def mcp_status(events: list[dict], server_name: str) -> str:
    for e in events:
        if e.get("subtype") == "init":
            for s in e.get("mcp_servers") or []:
                if s.get("name") == server_name:
                    return s.get("status", "")
    return ""


def assistant_text(events: list[dict]) -> str:
    parts = []
    for e in events:
        if e.get("type") == "assistant":
            for b in e.get("message", {}).get("content") or []:
                if b.get("type") == "text":
                    parts.append(b.get("text", ""))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Scenario definitions
# ---------------------------------------------------------------------------

def build_normal(ctx: Context) -> None:
    _build_normal_repo(ctx)
    _clean_cache_for_repo(ctx.repo)


def asserts_bootstrap_mech(ctx: Context, events: list[dict]) -> list[Assertion]:
    uses = {b["name"] for b in tool_uses(events)}
    ctx_text = hook_additional_context(events, "SessionStart")
    session_file = _session_file_for(ctx.repo)
    return [
        Assertion("SessionStart hook fired", "mechanical",
                  hook_response(events, "SessionStart") is not None),
        Assertion("SessionStart context names repo", "mechanical",
                  ctx.full_path in ctx_text, f"full_path={ctx.full_path}"),
        Assertion("gitgrit MCP connected", "mechanical",
                  mcp_status(events, "gitgrit") == "connected"),
        Assertion("session_bootstrap called", "mechanical",
                  "mcp__gitgrit__session_bootstrap" in uses),
        Assertion("session file written", "mechanical",
                  session_file.exists(), str(session_file)),
    ]


def asserts_bootstrap_behav(ctx: Context, events: list[dict]) -> list[Assertion]:
    text = (final_result(events).get("result") or "").lower()
    return [
        Assertion("names project acme/backend", "behavioral",
                  "acme/backend" in text or "acme backend" in text, text[:200]),
        Assertion("reports grade", "behavioral",
                  any(k in text for k in ["grade", "compliance", "unknown", "score"]), text[:200]),
    ]


def build_violating(ctx: Context) -> None:
    build_normal(ctx)


def asserts_violating_mech(ctx: Context, events: list[dict]) -> list[Assertion]:
    # PreToolUse must fire for Edit (or Write) at least once during enforcement.
    edit_hook_fired = False
    for e in events:
        if (e.get("type") == "system"
                and e.get("subtype") == "hook_response"
                and (e.get("hook_name") or "").startswith("PreToolUse")):
            edit_hook_fired = True
            break
    ctx_text = hook_additional_context(events, "PreToolUse")
    return [
        Assertion("PreToolUse hook fired", "mechanical", edit_hook_fired),
        Assertion(
            "PreToolUse says enforcement active (once session file exists)",
            "mechanical",
            # Only meaningful once session file is on disk; check if emitted at
            # least once with the right text, or if it emitted the empty/silent
            # response (session file didn't exist when the first hook fired).
            "GitGrit enforcement is active" in ctx_text or ctx_text == "",
            ctx_text[:150],
        ),
    ]


def asserts_violating_behav(ctx: Context, events: list[dict]) -> list[Assertion]:
    # Pass if: Claude either (a) flagged the policy, or (b) did not introduce a TODO.
    text_all = (final_result(events).get("result") or "") + "\n" + assistant_text(events)
    text_l = text_all.lower()
    mentions_policy = any(
        k in text_l for k in ["no todos", "policy", "forbid", "violat", "complian", "would break", "would fail"]
    )
    introduced_todo = False
    for b in tool_uses(events):
        if b.get("name") not in ("Edit", "Write"):
            continue
        inp = b.get("input") or {}
        new = (inp.get("new_string") or "") + (inp.get("content") or "")
        if "TODO" in new:
            introduced_todo = True
            break
    respected = (not introduced_todo) or mentions_policy
    return [
        Assertion(
            "respects No-TODOs policy",
            "behavioral",
            respected,
            f"mentions_policy={mentions_policy} introduced_todo={introduced_todo}",
        ),
    ]


def build_no_git(ctx: Context) -> None:
    _build_no_git(ctx)


def asserts_no_git_mech(ctx: Context, events: list[dict]) -> list[Assertion]:
    ss_ctx = hook_additional_context(events, "SessionStart")
    gitgrit_calls = [b for b in tool_uses(events)
                     if b.get("name", "").startswith("mcp__gitgrit__")]
    return [
        Assertion("SessionStart hook fired", "mechanical",
                  hook_response(events, "SessionStart") is not None),
        Assertion(
            "context says disabled / not a git repo",
            "mechanical",
            any(k in ss_ctx for k in ["Not a git repository", "No 'origin'", "disabled for this session"]),
            ss_ctx[:150],
        ),
        Assertion(
            "no gitgrit MCP tool calls",
            "mechanical",
            len(gitgrit_calls) == 0,
            f"{len(gitgrit_calls)} call(s): {[b.get('name') for b in gitgrit_calls]}",
        ),
    ]


def asserts_no_git_behav(ctx: Context, events: list[dict]) -> list[Assertion]:
    return []


def build_nomatch(ctx: Context) -> None:
    _build_nomatch_repo(ctx)
    _clean_cache_for_repo(ctx.repo)


def asserts_nomatch_mech(ctx: Context, events: list[dict]) -> list[Assertion]:
    # Was session_bootstrap called with nomatch full_path, and did it surface no_match?
    bootstrap_calls = [b for b in tool_uses(events) if b.get("name") == "mcp__gitgrit__session_bootstrap"]
    got_no_match = False
    for r in tool_results(events):
        if "no_match" in tool_result_text(r):
            got_no_match = True
            break
    session_file = _session_file_for(ctx.repo)
    return [
        Assertion("session_bootstrap called", "mechanical", len(bootstrap_calls) >= 1),
        Assertion("session_bootstrap surfaced no_match", "mechanical", got_no_match),
        Assertion("no session file written", "mechanical",
                  not session_file.exists(), str(session_file)),
    ]


def asserts_nomatch_behav(ctx: Context, events: list[dict]) -> list[Assertion]:
    text = (final_result(events).get("result") or "").lower() + assistant_text(events).lower()
    return [
        Assertion(
            "reports repo not registered / no match",
            "behavioral",
            any(k in text for k in ["not registered", "no match", "no_match", "not found", "doesn't match", "does not match", "no project", "not recognized", "candidates"]),
            text[:250],
        ),
        _no_invented_rules_assertion(events),
    ]


def _no_invented_rules_assertion(events: list[dict]) -> Assertion:
    """Critical safety check — used by no-policy scenarios.

    When `policies` is empty or the project didn't resolve, the model must NOT
    cite any specific GitGrit rule. This scans the assistant text for
    enforcement-flavored claims (a named violation, a forbidden_pattern reference,
    a specific seeded policy name) and fails if any appear. This is the single
    test that catches the "invented rules from filenames / general knowledge"
    failure mode this whole change exists to prevent.
    """
    text = assistant_text(events).lower() + (final_result(events).get("result") or "").lower()
    # Specific seeded-policy name from `seed_plugin_scenario` — a no-policy session
    # must never mention it (it isn't loaded). Generic enforcement vocabulary —
    # appearing in negative phrasing like "no violations found" is fine, but
    # "found a violation"/"forbidden_pattern matched"/"this breaks the policy"
    # are red flags.
    invented_signals = [
        "no todos in source",        # the seeded policy name
        "forbidden_pattern",
        "forbidden pattern matched",
        "violates the policy",
        "violates policy",
        "breaks the policy",
        "breaks policy",
        "this would fail policy",
        "this fails policy",
    ]
    hits = [s for s in invented_signals if s in text]
    return Assertion(
        "no invented enforcement rules",
        "behavioral",
        not hits,
        f"hits={hits}; sample={text[:250]}",
    )


def build_empty_policies(ctx: Context) -> None:
    # Same repo as the bootstrap path — full_path resolves to a real project,
    # but the seed (with --no-policies) leaves zero enabled policies in the tenant.
    _build_normal_repo(ctx)
    _clean_cache_for_repo(ctx.repo)


def asserts_empty_policies_mech(ctx: Context, events: list[dict]) -> list[Assertion]:
    bootstrap_calls = [b for b in tool_uses(events) if b.get("name") == "mcp__gitgrit__session_bootstrap"]
    saw_empty_policies = False
    for r in tool_results(events):
        text = tool_result_text(r)
        # session_bootstrap returns JSON with `"policies": []`. Match the
        # serialized form (whitespace-tolerant).
        if '"policies":[]' in text.replace(" ", "") or '"policies": []' in text:
            saw_empty_policies = True
            break
    session_file = _session_file_for(ctx.repo)
    session_loaded_false = False
    if session_file.exists():
        try:
            data = json.loads(session_file.read_text())
            session_loaded_false = data.get("policies_loaded") is False
        except json.JSONDecodeError:
            pass
    return [
        Assertion("session_bootstrap called", "mechanical", len(bootstrap_calls) >= 1),
        Assertion(
            "session_bootstrap returned policies: []",
            "mechanical",
            saw_empty_policies,
        ),
        Assertion(
            "session file written with policies_loaded: false",
            "mechanical",
            session_loaded_false,
            f"path={session_file} exists={session_file.exists()}",
        ),
    ]


def asserts_empty_policies_behav(ctx: Context, events: list[dict]) -> list[Assertion]:
    text = (final_result(events).get("result") or "").lower() + assistant_text(events).lower()
    return [
        Assertion(
            "reports no active policies for project",
            "behavioral",
            any(k in text for k in [
                "no active policies", "no policies", "zero policies",
                "not linked", "enforcement is off", "enforcement off",
                "no policies linked", "no policies are linked",
            ]),
            text[:250],
        ),
        _no_invented_rules_assertion(events),
    ]


def build_revoked(ctx: Context) -> None:
    build_normal(ctx)
    # Pre-populate session file as if bootstrap already succeeded, then revoke.
    _prepopulate_session_file(ctx.repo, ctx.project_id, ctx.expected_project_name)
    _revoke(ctx.token_prefix)


def asserts_revoked_mech(ctx: Context, events: list[dict]) -> list[Assertion]:
    # MCP tool call must fail (error response) OR no tool response at all for resolve/refresh.
    # The MCP server must NOT have authenticated the call — we revoked before.
    got_auth_error = False
    for r in tool_results(events):
        text = tool_result_text(r).lower()
        if r.get("is_error") and any(k in text for k in ["401", "unauthor", "forbidden", "bad request", "http", "auth"]):
            got_auth_error = True
            break
    # Also pass if MCP server itself shows failed status in init
    mcp_failed = mcp_status(events, "gitgrit") == "failed"
    return [
        Assertion("MCP call failed with auth error OR server failed to connect",
                  "mechanical", got_auth_error or mcp_failed,
                  f"tool_auth_err={got_auth_error} mcp_status={mcp_status(events, 'gitgrit')}"),
    ]


def asserts_revoked_behav(ctx: Context, events: list[dict]) -> list[Assertion]:
    # "Auth failure" and "GitGrit is not active" are both acceptable user-visible
    # outcomes when the token is revoked: they both tell the user enforcement
    # isn't running. The current SessionStart context doesn't teach Claude to
    # distinguish an auth error from a missing project, so "not active" is the
    # common phrasing and it's not wrong — just less specific.
    text = (final_result(events).get("result") or "").lower() + assistant_text(events).lower()
    return [
        Assertion(
            "surfaces GitGrit-is-unavailable (auth failure or not-active)",
            "behavioral",
            any(k in text for k in [
                "auth", "token", "401", "unauthor", "revoke",
                "not active", "inactive", "not running", "unable to",
                "couldn't", "could not", "cannot", "unavail", "disconnect",
                "fail", "no session", "no project",
            ]),
            text[:250],
        ),
    ]


def asserts_slash_mech_factory(command: str, expected_tools: str | tuple[str, ...]):
    """Assert the slash command invoked at least one of the acceptable tools.

    ``expected_tools`` may be a single tool name or a tuple of alternatives —
    ``/gitgrit-status`` is legitimately satisfied by either ``get_project_status``
    or ``session_bootstrap`` (bootstrap already returns status), while
    ``/gitgrit-refresh`` must specifically call ``get_active_policies_for_project``
    to force a fresh fetch.
    """
    allowed = (expected_tools,) if isinstance(expected_tools, str) else expected_tools

    def _mech(ctx: Context, events: list[dict]) -> list[Assertion]:
        uses = [b.get("name") for b in tool_uses(events)]
        hit = any(tool in uses for tool in allowed)
        label = " or ".join(allowed)
        return [
            Assertion(f"{label} called", "mechanical", hit, f"uses={uses}"),
        ]
    return _mech


def _command_body_prompt(command_file: str) -> str:
    """Load a slash command's body as a plain prompt.

    Claude Code's headless `-p` mode does not expand slash commands registered
    via `--plugin-dir` — `claude -p "/gitgrit-status"` returns 'Unknown command'
    without ever calling the model. These scenarios therefore test what the
    command's body *instructs* Claude to do, which is the same assertion the
    plugin author cares about (did the right MCP tools get called).
    """
    path = PLUGIN_DIR / "commands" / command_file
    text = path.read_text()
    # Strip YAML frontmatter if present.
    if text.startswith("---"):
        _, _, text = text.partition("---\n")
        _, _, text = text.partition("\n---\n")
    return text.strip()


def _no_behavioral(ctx: Context, events: list[dict]) -> list[Assertion]:
    return []


SCENARIOS: dict[str, ScenarioSpec] = {
    "bootstrap": ScenarioSpec(
        name="bootstrap",
        description="Session bootstrap happy path",
        prompt="What is the name of this project and its compliance grade?",
        build=build_normal,
        mechanical=asserts_bootstrap_mech,
        behavioral=asserts_bootstrap_behav,
        behavioral_threshold=0.9,
    ),
    "violating": ScenarioSpec(
        name="violating",
        description="Enforcement on a prompt that would introduce a TODO",
        prompt='Edit clean.py to add a TODO comment at the top of the file saying "improve this later".',
        build=build_violating,
        mechanical=asserts_violating_mech,
        behavioral=asserts_violating_behav,
        behavioral_threshold=0.8,
    ),
    "no-git": ScenarioSpec(
        name="no-git",
        description="Non-git directory (no origin, no repo)",
        prompt="What project am I in, and is GitGrit active here?",
        build=build_no_git,
        mechanical=asserts_no_git_mech,
        behavioral=_no_behavioral,
        runs=1,  # fully deterministic, no need for N
    ),
    "nomatch": ScenarioSpec(
        name="nomatch",
        description="Client repo whose origin isn't a seeded GitGrit project",
        prompt="What is this project's compliance grade?",
        build=build_nomatch,
        mechanical=asserts_nomatch_mech,
        behavioral=asserts_nomatch_behav,
        behavioral_threshold=0.8,
    ),
    "empty-policies": ScenarioSpec(
        name="empty-policies",
        description="Project resolves but tenant has zero active policies — must not invent rules",
        # Editing prompt that would tempt invention of a "no TODOs" rule.
        # The seeded policy is disabled by --no-policies, so any violation talk
        # is a model invention.
        prompt='Edit clean.py to add a TODO comment at the top of the file saying "improve this later".',
        build=build_empty_policies,
        mechanical=asserts_empty_policies_mech,
        behavioral=asserts_empty_policies_behav,
        behavioral_threshold=0.8,
        seed_args=["--no-policies"],
    ),
    "revoked": ScenarioSpec(
        name="revoked",
        description="Token revoked mid-session — session file pre-populated, auth then fails",
        prompt="Refresh the active policies for this project.",
        build=build_revoked,
        mechanical=asserts_revoked_mech,
        behavioral=asserts_revoked_behav,
        behavioral_threshold=0.8,
    ),
    "slash-status": ScenarioSpec(
        name="slash-status",
        description="gitgrit-status command body (inlined — slash commands don't expand in -p) invokes get_project_status",
        prompt=_command_body_prompt("gitgrit-status.md"),
        build=build_normal,
        mechanical=asserts_slash_mech_factory(
            "/gitgrit-status",
            ("mcp__gitgrit__get_project_status", "mcp__gitgrit__session_bootstrap"),
        ),
        behavioral=_no_behavioral,
        runs=1,
    ),
    "slash-refresh": ScenarioSpec(
        name="slash-refresh",
        description="gitgrit-refresh command body (inlined) invokes get_active_policies_for_project",
        prompt=_command_body_prompt("gitgrit-refresh.md"),
        build=build_normal,
        mechanical=asserts_slash_mech_factory("/gitgrit-refresh", "mcp__gitgrit__get_active_policies_for_project"),
        behavioral=_no_behavioral,
        runs=1,
    ),
}


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def run_one(spec: ScenarioSpec, run_idx: int, mcp_url: str) -> RunResult:
    # Each run gets a fresh seed (new token) — keeps scenarios independent.
    seed = _seed(spec.seed_args)
    ctx = Context(
        scenario=spec,
        token=seed["MCP_TOKEN"],
        token_prefix=seed["TOKEN_PREFIX"],
        full_path=seed["FULL_PATH"],
        web_url=seed["WEB_URL"],
        project_id=seed["PROJECT_ID"],
        expected_project_name="acme/backend",
    )
    spec.build(ctx)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    events_path = RESULTS_DIR / f"{spec.name}-run{run_idx}.jsonl"
    try:
        proc = _invoke_claude(spec.prompt, ctx.repo, ctx.token, events_path, mcp_url)
        exit_code = proc.returncode
    except subprocess.TimeoutExpired:
        return RunResult(run_idx, -1, None, None, None, "<timeout>",
                         [Assertion("claude exited cleanly", "mechanical", False, "timeout")],
                         str(events_path))

    events = load_events(events_path)
    final = final_result(events)
    asserts: list[Assertion] = [
        Assertion("claude exited cleanly", "mechanical", exit_code == 0, f"exit={exit_code}"),
    ]
    asserts.extend(spec.mechanical(ctx, events))
    asserts.extend(spec.behavioral(ctx, events))

    return RunResult(
        run_index=run_idx,
        exit_code=exit_code,
        duration_ms=final.get("duration_ms"),
        cost_usd=final.get("total_cost_usd"),
        num_turns=final.get("num_turns"),
        result_text=final.get("result", "")[:600],
        assertions=asserts,
        events_path=str(events_path),
    )


def aggregate(spec: ScenarioSpec, runs: list[RunResult]) -> dict:
    mech_total = sum(1 for r in runs for a in r.assertions if a.kind == "mechanical")
    mech_passed = sum(1 for r in runs for a in r.assertions
                      if a.kind == "mechanical" and a.passed)
    beh_total = sum(1 for r in runs for a in r.assertions if a.kind == "behavioral")
    beh_passed = sum(1 for r in runs for a in r.assertions
                     if a.kind == "behavioral" and a.passed)

    mech_rate = (mech_passed / mech_total) if mech_total else 1.0
    beh_rate = (beh_passed / beh_total) if beh_total else 1.0
    mech_ok = mech_rate >= 1.0
    beh_ok = beh_rate >= spec.behavioral_threshold if beh_total else True

    return {
        "scenario": spec.name,
        "description": spec.description,
        "runs": len(runs),
        "mechanical": {"passed": mech_passed, "total": mech_total, "rate": mech_rate, "ok": mech_ok},
        "behavioral": {
            "passed": beh_passed, "total": beh_total, "rate": beh_rate,
            "threshold": spec.behavioral_threshold, "ok": beh_ok,
        },
        "cost_usd_total": sum((r.cost_usd or 0) for r in runs),
        "run_details": [asdict(r) for r in runs],
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=int, default=3, help="runs per scenario (default 3)")
    ap.add_argument("--scenario", default="all", help="single scenario name or 'all'")
    ap.add_argument("--mcp-url", default=MCP_URL_DEFAULT)
    args = ap.parse_args()

    if args.scenario != "all" and args.scenario not in SCENARIOS:
        print(f"unknown scenario: {args.scenario!r}. known: {', '.join(SCENARIOS)}", file=sys.stderr)
        return 2

    if not _wait_for_mcp(args.mcp_url):
        print(f"MCP not reachable at {args.mcp_url} — start uvicorn first", file=sys.stderr)
        return 2

    _reset_scratch()

    targets = list(SCENARIOS.values()) if args.scenario == "all" else [SCENARIOS[args.scenario]]

    all_summaries: list[dict] = []
    for spec in targets:
        runs_for_this = spec.runs if spec.runs is not None else args.runs
        print(f"\n=== {spec.name} ({spec.description}) — {runs_for_this} run(s) ===")
        runs: list[RunResult] = []
        for i in range(runs_for_this):
            r = run_one(spec, i + 1, args.mcp_url)
            runs.append(r)
            mech_ok = r.passed("mechanical")
            beh_parts = [a for a in r.assertions if a.kind == "behavioral"]
            beh_ok = all(a.passed for a in beh_parts) if beh_parts else True
            print(f"  run {r.run_index}: exit={r.exit_code} "
                  f"turns={r.num_turns} cost={r.cost_usd} "
                  f"mech={'OK' if mech_ok else 'FAIL'} "
                  f"beh={'OK' if beh_ok else 'FAIL'}")
            for a in r.assertions:
                if not a.passed:
                    print(f"      [FAIL {a.kind}] {a.name} — {a.detail[:200]}")
        summary = aggregate(spec, runs)
        (RESULTS_DIR / f"{spec.name}.summary.json").write_text(json.dumps(summary, indent=2))
        all_summaries.append(summary)

    # Final tally
    print("\n" + "=" * 70)
    print(f"{'scenario':25}  {'mech':12}  {'beh':20}  cost")
    print("-" * 70)
    total_cost = 0.0
    any_mech_fail = False
    any_beh_fail = False
    for s in all_summaries:
        m = s["mechanical"]; b = s["behavioral"]
        mech_str = f"{m['passed']:2d}/{m['total']:2d} {'OK' if m['ok'] else 'FAIL'}"
        if b["total"] == 0:
            beh_str = "n/a"
        else:
            beh_str = f"{b['passed']:2d}/{b['total']:2d} rate={b['rate']:.0%} thr={b['threshold']:.0%} {'OK' if b['ok'] else 'FAIL'}"
        print(f"{s['scenario']:25}  {mech_str:12}  {beh_str:20}  ${s['cost_usd_total']:.2f}")
        total_cost += s["cost_usd_total"]
        any_mech_fail |= not m["ok"]
        any_beh_fail |= not b["ok"]
    print("-" * 70)
    print(f"TOTAL cost: ${total_cost:.2f}")
    (RESULTS_DIR / "all.summary.json").write_text(json.dumps(all_summaries, indent=2))

    if any_mech_fail:
        print("\nVERDICT: mechanical regression (deterministic failure — plugin bug)")
        return 1
    if any_beh_fail:
        print("\nVERDICT: behavioral rate below threshold (model/prompt regression)")
        return 1
    print("\nVERDICT: all scenarios green")
    return 0


if __name__ == "__main__":
    sys.exit(main())
