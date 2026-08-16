from types import SimpleNamespace

from django.test import TestCase
from model_bakery import baker

from app.application import dependency_agent as da
from app.domain.models import (
    ExternalDependency,
    InfrastructureComponent,
    Project,
    ProjectDependency,
)
from tests.support import MonkeyPatchMixin


class DependencyAgentTests(MonkeyPatchMixin, TestCase):
    def _setup(self, result):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        src = baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            name="web",
            full_path="org/web",
        )
        api = baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            name="api",
            full_path="org/api",
        )
        # Avoid network + LLM: stub the client and the agent's model call.
        self.monkeypatch.setattr(
            da,
            "resolve_llm_roles",
            lambda t: {
                "reasoning": {
                    "model": "anthropic/claude",
                    "base_url": "",
                    "api_key": "k",
                }
            },
        )
        self.monkeypatch.setattr(
            da, "get_platform_client", lambda c: SimpleNamespace()
        )
        self.monkeypatch.setattr(da.LLMAgent, "run", lambda self, **kw: result)
        return tenant, src, api

    def test_writes_internal_and_external_edges(self):
        result = da.DependencyResult(
            technologies=["Express", "Express", "Next.js"],  # dup → deduped
            internal=[{"target": "org/api", "label": "REST"}],
            external_providers=[
                {"name": "Stripe", "url": "https://stripe.com", "label": "payments"}
            ],
            external_consumers=[{"name": "Partner API", "label": "public"}],
        )
        _tenant, src, api = self._setup(result)

        da.infer_and_store(src)

        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)
        self.assertIsNotNone(src.deps_analyzed_at)
        self.assertEqual(src.inferred_technologies, ["Express", "Next.js"])

        pd = ProjectDependency.objects.get(source=src)
        self.assertEqual(pd.target_id, api.id)
        self.assertEqual(pd.label, "REST")

        provider = ExternalDependency.objects.get(
            project=src, direction=ExternalDependency.Direction.OUTBOUND
        )
        self.assertEqual(provider.name, "Stripe")
        self.assertEqual(provider.url, "https://stripe.com")

        consumer = ExternalDependency.objects.get(
            project=src, direction=ExternalDependency.Direction.INBOUND
        )
        self.assertEqual(consumer.name, "Partner API")

    def test_unresolved_internal_target_is_skipped(self):
        result = da.DependencyResult(
            internal=[{"target": "org/does-not-exist"}],
            external=[],
        )
        _tenant, src, _api = self._setup(result)

        da.infer_and_store(src)

        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 0)
        # Ran fine, just nothing resolved.
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)

    def test_rerun_replaces_edges_atomically(self):
        _tenant, src, _api = self._setup(
            da.DependencyResult(
                internal=[{"target": "org/api"}],
                external_providers=[{"name": "Stripe"}],
            ),
        )
        da.infer_and_store(src)
        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 1)
        self.assertEqual(ExternalDependency.objects.filter(project=src).count(), 1)

        # Re-run with a different result — old edges must be gone.
        self.monkeypatch.setattr(
            da.LLMAgent,
            "run",
            lambda self, **kw: da.DependencyResult(
                internal=[], external_providers=[{"name": "Auth0"}]
            ),
        )
        da.infer_and_store(src)

        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 0)
        names = list(
            ExternalDependency.objects.filter(project=src).values_list(
                "name", flat=True
            )
        )
        self.assertEqual(names, ["Auth0"])

    def test_infrastructure_backstop_and_external_dedup(self):
        result = da.DependencyResult(
            infrastructure=[{"name": "Redis", "kind": "cache"}],
            external_providers=[
                {"name": "Stripe"},
                {"name": "Stripe API"},  # same service → deduped
                {"name": "PostgreSQL"},  # datastore → backstop moves to infra
            ],
        )
        _tenant, src, _api = self._setup(result)

        da.infer_and_store(src)

        infra = set(
            InfrastructureComponent.objects.filter(project=src).values_list(
                "name", "kind"
            )
        )
        self.assertIn(("Redis", "cache"), infra)
        self.assertIn(("PostgreSQL", "database"), infra)  # reclassified by backstop

        providers = list(
            ExternalDependency.objects.filter(
                project=src, direction=ExternalDependency.Direction.OUTBOUND
            ).values_list("name", flat=True)
        )
        # "Stripe API" deduped; PostgreSQL moved to infrastructure.
        self.assertEqual(providers, ["Stripe"])

    def test_missing_reasoning_role_raises(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        src = baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            full_path="org/web",
        )
        self.monkeypatch.setattr(da, "resolve_llm_roles", lambda t: {})

        with self.assertRaises(RuntimeError):
            da.infer_and_store(src)
