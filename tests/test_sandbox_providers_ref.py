"""Sandbox providers read the repository at the run's ref, falling back to the
default branch when no ref is given."""
import sys
from pathlib import Path
from unittest import mock

SANDBOX_DIR = Path(__file__).resolve().parents[1] / "sandbox_image"
if str(SANDBOX_DIR) not in sys.path:
    sys.path.insert(0, str(SANDBOX_DIR))

from providers.github import GitHubProvider
from providers.gitlab import GitLabProvider


def test_github_reads_at_ref():
    p = GitHubProvider("1", "tok", full_path="acme/repo", ref="develop")
    with mock.patch.object(p, "_get", return_value={"tree": []}) as get, mock.patch.object(
        p, "_get_raw", return_value="x"
    ) as raw:
        p.list_files()
        p.get_file_content("README.md")
        p.get_file_last_commit_date("README.md")
    assert get.call_args_list[0].args[0] == "/repos/acme/repo/git/trees/develop?recursive=1"
    assert raw.call_args.args[0] == "/repos/acme/repo/contents/README.md?ref=develop"
    assert "&sha=develop&" in get.call_args_list[1].args[0]


def test_github_falls_back_to_default_branch():
    p = GitHubProvider("1", "tok", full_path="acme/repo")
    p._repo_cache = {"default_branch": "master"}
    with mock.patch.object(p, "_get", return_value={"tree": []}) as get:
        p.list_files()
    assert get.call_args.args[0] == "/repos/acme/repo/git/trees/master?recursive=1"


def test_gitlab_reads_at_ref():
    p = GitLabProvider("7", "tok", full_path="acme/repo", ref="release/1.0")
    with mock.patch.object(p, "_get", return_value=[]) as get, mock.patch.object(
        p, "_get_raw", return_value="x"
    ) as raw:
        p.list_files()
        p.get_file_content("README.md")
    assert "?ref=release%2F1.0&" in get.call_args.args[0]
    assert raw.call_args.args[0].endswith("/raw?ref=release%2F1.0")


def test_gitlab_falls_back_to_default_branch():
    p = GitLabProvider("7", "tok", full_path="acme/repo")
    p._project_cache = {"default_branch": "master"}
    with mock.patch.object(p, "_get", return_value=[]) as get:
        p.list_files()
    assert "?ref=master&" in get.call_args.args[0]
