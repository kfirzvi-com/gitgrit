import pytest
from model_bakery import baker

from app.application import dependency_agent as da
from app.domain.models import ExternalDependency, Project, ProjectDependency


def _setup(monkeypatch, result):
    tenant = baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
    src = baker.make(
        "app.Project", tenant=tenant, platform_connection=conn,
        name="web", full_path="org/web",
    )
    api = baker.make(
        "app.Project", tenant=tenant, platform_connection=conn,
        name="api", full_path="org/api",
    )
    # Avoid network + LLM: stub the client and the agent's model call.
    monkeypatch.setattr(da, "resolve_llm_roles", lambda t: {
        "reasoning": {"model": "anthropic/claude", "base_url": "", "api_key": "k"}
    })
    monkeypatch.setattr(da, "get_platform_client", lambda c: object())
    monkeypatch.setattr(da.LLMAgent, "run", lambda self, **kw: result)
    return tenant, src, api


@pytest.mark.django_db
def test_writes_internal_and_external_edges(monkeypatch):
    result = da.DependencyResult(
        internal=[{"target": "org/api", "label": "REST"}],
        external=[{"name": "Stripe", "url": "https://stripe.com", "label": "payments"}],
    )
    tenant, src, api = _setup(monkeypatch, result)

    da.infer_and_store(src)

    src.refresh_from_db()
    assert src.deps_status == Project.DepsStatus.OK
    assert src.deps_analyzed_at is not None

    pd = ProjectDependency.objects.get(source=src)
    assert pd.target_id == api.id and pd.label == "REST"

    ed = ExternalDependency.objects.get(project=src)
    assert ed.name == "Stripe" and ed.url == "https://stripe.com"


@pytest.mark.django_db
def test_unresolved_internal_target_is_skipped(monkeypatch):
    result = da.DependencyResult(
        internal=[{"target": "org/does-not-exist"}],
        external=[],
    )
    tenant, src, api = _setup(monkeypatch, result)

    da.infer_and_store(src)

    assert ProjectDependency.objects.filter(source=src).count() == 0
    assert src.deps_status == Project.DepsStatus.OK  # ran fine, just nothing resolved


@pytest.mark.django_db
def test_rerun_replaces_edges_atomically(monkeypatch):
    tenant, src, api = _setup(
        monkeypatch,
        da.DependencyResult(
            internal=[{"target": "org/api"}],
            external=[{"name": "Stripe"}],
        ),
    )
    da.infer_and_store(src)
    assert ProjectDependency.objects.filter(source=src).count() == 1
    assert ExternalDependency.objects.filter(project=src).count() == 1

    # Re-run with a different result — old edges must be gone.
    monkeypatch.setattr(
        da.LLMAgent, "run",
        lambda self, **kw: da.DependencyResult(internal=[], external=[{"name": "Auth0"}]),
    )
    da.infer_and_store(src)
    assert ProjectDependency.objects.filter(source=src).count() == 0
    names = list(ExternalDependency.objects.filter(project=src).values_list("name", flat=True))
    assert names == ["Auth0"]


@pytest.mark.django_db
def test_missing_reasoning_role_raises(monkeypatch):
    tenant = baker.make("app.Tenant")
    conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
    src = baker.make("app.Project", tenant=tenant, platform_connection=conn, full_path="org/web")
    monkeypatch.setattr(da, "resolve_llm_roles", lambda t: {})
    with pytest.raises(RuntimeError):
        da.infer_and_store(src)
