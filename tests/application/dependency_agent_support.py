"""Shared fixture for the ``infer_and_store`` tests: one workspace with two
projects, the LLM role, the platform client and the model stubbed so nothing
leaves the process.

``make_workspace`` is the whole setup; ``fake_client`` and ``fake_model`` are
exposed so a test can hand in its own tree or re-stub the model mid-test.
"""
from __future__ import annotations

from types import SimpleNamespace

from model_bakery import baker

from app.application import dependency_agent as da
from app.infrastructure.topology import llm_inference as li

LLM_ROLES = {"reasoning": {"model": "anthropic/claude", "base_url": "", "api_key": "k"}}


def fake_client(tree=("README.md", "package.json"), files=None):
    """An in-memory platform client: ``tree`` is the file list, ``files`` maps path to content."""
    files = {"package.json": '{"name": "web"}'} if files is None else files
    return SimpleNamespace(
        get_tree=lambda full_path, ref: list(tree),
        get_file_content=lambda full_path, path, ref: files.get(path),
    )


def fake_model(*, discovery=None, deps=None, paths=("package.json",), inspect=True):
    """Stand in for ``LLMAgent.run``. ``deps`` is one ``DependencyResult`` for
    every component, or a ``{path: DependencyResult}`` map. With ``inspect``
    the model lists the tree and reads ``paths`` first, like a real one."""
    discovery = discovery or li.ComponentDiscovery(components=[])
    deps = deps if deps is not None else li.DependencyResult()

    def run(self, **kw):
        toolbox = kw["toolbox"]
        if inspect:
            toolbox.list_repo_files("")
        if kw["response_model"] is li.ComponentDiscovery:
            return discovery
        if inspect:
            for path in paths:
                toolbox.read_file(path)
        if isinstance(deps, dict):
            return deps.get(toolbox.scope, li.DependencyResult())
        return deps

    return run


def make_workspace(monkeypatch, client=None, *, sibling=("api", "org/api"), **model):
    """A tenant with ``web`` (``org/web``) and one sibling project, the LLM
    role resolved to a dummy, the platform client set to ``client`` (or
    ``fake_client()``) and the model to ``fake_model(**model)``.
    Returns ``(tenant, web, sibling)``."""
    tenant = baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
    web = baker.make("app.Project", tenant=tenant, platform_connection=conn, name="web", full_path="org/web")
    name, full_path = sibling
    other = baker.make("app.Project", tenant=tenant, platform_connection=conn, name=name, full_path=full_path)
    # Avoid network + LLM: stub the role lookup, the platform client and the model.
    monkeypatch.setattr(da, "resolve_llm_roles", lambda t: LLM_ROLES)
    monkeypatch.setattr(
        "app.infrastructure.topology.snapshots.get_platform_client", lambda c: client or fake_client()
    )
    monkeypatch.setattr(li.LLMAgent, "run", fake_model(**model))
    return tenant, web, other
