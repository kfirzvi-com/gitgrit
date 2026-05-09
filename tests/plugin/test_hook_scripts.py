"""Shell-plumbing tests for the two GitGrit plugin hook scripts.

No Django DB, no network, no Claude. Each test spins up a tiny real git repo
under tmp_path, invokes the script via subprocess (with a per-test
``XDG_CACHE_HOME`` so the real user cache is never touched), and asserts on
exit code and the JSON printed to stdout.
"""
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_INIT = REPO_ROOT / "plugin" / "scripts" / "session-init.sh"
ENFORCE_CHECK = REPO_ROOT / "plugin" / "scripts" / "enforce-check.sh"


def _run(script: Path, cwd: Path, cache_home: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ}
    if cache_home is not None:
        env["XDG_CACHE_HOME"] = str(cache_home)
    return subprocess.run(
        ["bash", str(script)],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        env=env,
    )


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(
        ["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True
    )


def _make_repo(path: Path, origin: str | None = None) -> None:
    path.mkdir(parents=True, exist_ok=True)
    _git("init", cwd=path)
    if origin is not None:
        _git("remote", "add", "origin", origin, cwd=path)


def _expected_session_file(repo: Path, cache_home: Path) -> Path:
    """Compute the session file path the hooks will derive for ``repo``.

    Must match the logic in session-init.sh / enforce-check.sh: SHA-256 of the
    absolute .git dir, first 16 hex chars, under $XDG_CACHE_HOME/gitgrit/.
    """
    abs_git_dir = subprocess.check_output(
        ["git", "rev-parse", "--absolute-git-dir"], cwd=str(repo), text=True
    ).strip()
    digest = hashlib.sha256(abs_git_dir.encode()).hexdigest()[:16]
    return cache_home / "gitgrit" / f"{digest}.json"


class TestSessionInitNotGit:
    def test_non_git_dir_emits_disabled_context(self, tmp_path: Path) -> None:
        result = _run(SESSION_INIT, cwd=tmp_path, cache_home=tmp_path / "xdg_cache")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert (
            "Not a git repository"
            in payload["hookSpecificOutput"]["additionalContext"]
        )


class TestSessionInitNoOrigin:
    def test_git_repo_without_origin_emits_disabled_context(
        self, tmp_path: Path
    ) -> None:
        _make_repo(tmp_path)

        result = _run(SESSION_INIT, cwd=tmp_path, cache_home=tmp_path / "xdg_cache")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert (
            "No 'origin' git remote"
            in payload["hookSpecificOutput"]["additionalContext"]
        )


class TestSessionInitUrlNormalization:
    @pytest.mark.parametrize(
        "origin,expected_full_path,expected_web_url",
        [
            (
                "https://github.com/acme/backend.git",
                "acme/backend",
                "https://github.com/acme/backend",
            ),
            (
                "https://github.com/acme/backend",
                "acme/backend",
                "https://github.com/acme/backend",
            ),
            (
                "https://alice:s3cret@github.com/acme/backend.git",
                "acme/backend",
                "https://github.com/acme/backend",
            ),
            (
                "git@github.com:acme/backend.git",
                "acme/backend",
                "https://github.com/acme/backend",
            ),
            (
                "git@github.com:acme/backend",
                "acme/backend",
                "https://github.com/acme/backend",
            ),
            (
                "https://gitlab.example.com/group/sub/repo.git",
                "group/sub/repo",
                "https://gitlab.example.com/group/sub/repo",
            ),
        ],
    )
    def test_origin_form_normalizes(
        self,
        tmp_path: Path,
        origin: str,
        expected_full_path: str,
        expected_web_url: str,
    ) -> None:
        _make_repo(tmp_path, origin=origin)

        result = _run(SESSION_INIT, cwd=tmp_path, cache_home=tmp_path / "xdg_cache")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert f'repo_full_path="{expected_full_path}"' in ctx
        assert f'web_url="{expected_web_url}"' in ctx

    def test_credentials_are_never_leaked_into_context(self, tmp_path: Path) -> None:
        _make_repo(
            tmp_path, origin="https://alice:super-secret-token@github.com/acme/backend.git"
        )

        result = _run(SESSION_INIT, cwd=tmp_path, cache_home=tmp_path / "xdg_cache")

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert "super-secret-token" not in ctx
        assert "alice:" not in ctx

    def test_session_file_path_is_in_xdg_cache(self, tmp_path: Path) -> None:
        _make_repo(tmp_path, origin="https://github.com/acme/backend.git")
        cache = tmp_path / "xdg_cache"

        result = _run(SESSION_INIT, cwd=tmp_path, cache_home=cache)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        expected = _expected_session_file(tmp_path, cache)
        assert str(expected) in ctx
        # Must never instruct Claude to write inside .git/ — Claude Code blocks that path.
        assert "/.git/" not in ctx.split("content:")[0]

    def test_session_init_creates_cache_dir(self, tmp_path: Path) -> None:
        _make_repo(tmp_path, origin="https://github.com/acme/backend.git")
        cache = tmp_path / "xdg_cache"

        result = _run(SESSION_INIT, cwd=tmp_path, cache_home=cache)

        assert result.returncode == 0, result.stderr
        assert (cache / "gitgrit").is_dir()


def _write_session(repo: Path, cache: Path, data: str) -> None:
    sf = _expected_session_file(repo, cache)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text(data)


class TestEnforceCheckSilentCases:
    def test_not_in_git_repo_exits_silently(self, tmp_path: Path) -> None:
        result = _run(ENFORCE_CHECK, cwd=tmp_path, cache_home=tmp_path / "xdg_cache")

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_session_file_missing_exits_silently(self, tmp_path: Path) -> None:
        _make_repo(tmp_path)

        result = _run(ENFORCE_CHECK, cwd=tmp_path, cache_home=tmp_path / "xdg_cache")

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""

    def test_malformed_session_json_exits_silently(self, tmp_path: Path) -> None:
        _make_repo(tmp_path)
        cache = tmp_path / "xdg_cache"
        _write_session(tmp_path, cache, "not json at all {")

        result = _run(ENFORCE_CHECK, cwd=tmp_path, cache_home=cache)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""


class TestEnforceCheckEmitsReminder:
    def test_valid_session_json_emits_pretooluse_context(self, tmp_path: Path) -> None:
        _make_repo(tmp_path)
        cache = tmp_path / "xdg_cache"
        _write_session(
            tmp_path,
            cache,
            json.dumps(
                {
                    "version": 2,
                    "project_id": "abc",
                    "project_name": "acme/backend",
                    "policies_loaded": True,
                }
            ),
        )

        result = _run(ENFORCE_CHECK, cwd=tmp_path, cache_home=cache)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert payload["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
        ctx = payload["hookSpecificOutput"]["additionalContext"]
        assert "GitGrit enforcement is active" in ctx
        assert "acme/backend" in ctx

    def test_session_json_missing_project_name_falls_back_to_unknown(
        self, tmp_path: Path
    ) -> None:
        _make_repo(tmp_path)
        cache = tmp_path / "xdg_cache"
        _write_session(
            tmp_path,
            cache,
            json.dumps({"version": 2, "project_id": "abc", "policies_loaded": True}),
        )

        result = _run(ENFORCE_CHECK, cwd=tmp_path, cache_home=cache)

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "(unknown)" in payload["hookSpecificOutput"]["additionalContext"]

    def test_enforce_check_ignores_stale_session_from_other_repo(
        self, tmp_path: Path
    ) -> None:
        # Two repos on disk → different absolute git dirs → different hash keys.
        # A session file from repo A must not activate enforcement in repo B.
        repo_a = tmp_path / "a"
        repo_b = tmp_path / "b"
        _make_repo(repo_a)
        _make_repo(repo_b)
        cache = tmp_path / "xdg_cache"
        _write_session(
            repo_a,
            cache,
            json.dumps({"version": 2, "project_id": "a", "project_name": "a/a", "policies_loaded": True}),
        )

        result = _run(ENFORCE_CHECK, cwd=repo_b, cache_home=cache)

        assert result.returncode == 0, result.stderr
        assert result.stdout == ""
