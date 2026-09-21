from types import SimpleNamespace

from django.test import TestCase
from model_bakery import baker

from app.application import dependency_agent as da
from app.domain.models import (
    ComponentDependency,
    ExternalDependency,
    InfrastructureComponent,
    Project,
)
from tests.support import MonkeyPatchMixin


def _fake_client(tree=("README.md", "package.json"), files=None):
    files = {"package.json": '{"name": "web"}'} if files is None else files
    return SimpleNamespace(
        get_tree=lambda full_path, ref: list(tree),
        get_file_content=lambda full_path, path, ref: files.get(path),
    )


def _reading_run(result, paths=("package.json",)):
    """Stand in for LLMAgent.run: inspect the repo like a real model would
    (list, then read the given files), then return ``result``."""

    def run(self, **kw):
        toolbox = kw["toolbox"]
        toolbox.list_repo_files("")
        for path in paths:
            toolbox.read_file(path)
        return result

    return run


class DependencyAgentTests(MonkeyPatchMixin, TestCase):
    def _setup(self, result, client=None):
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
        client = client or _fake_client()
        self.monkeypatch.setattr(da, "get_platform_client", lambda c: client)
        self.monkeypatch.setattr(da.LLMAgent, "run", _reading_run(result))
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
        root = src.root_component
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)
        self.assertIsNotNone(src.deps_analyzed_at)
        self.assertEqual(root.technologies, ["Express", "Next.js"])
        self.assertEqual(src.deps_evidence, ["package.json"])

        # Edges hang off the root components of both repositories.
        pd = ComponentDependency.objects.get(source=root)
        self.assertEqual(pd.target, api.root_component)
        self.assertEqual(pd.label, "REST")

        provider = ExternalDependency.objects.get(
            component=root, direction=ExternalDependency.Direction.OUTBOUND
        )
        self.assertEqual(provider.name, "Stripe")
        self.assertEqual(provider.url, "https://stripe.com")

        consumer = ExternalDependency.objects.get(
            component=root, direction=ExternalDependency.Direction.INBOUND
        )
        self.assertEqual(consumer.name, "Partner API")

    def test_unresolved_internal_target_is_skipped(self):
        result = da.DependencyResult(internal=[{"target": "org/does-not-exist"}])
        _tenant, src, _api = self._setup(result)

        da.infer_and_store(src)

        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 0)
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
        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 1)
        self.assertEqual(ExternalDependency.objects.filter(component__project=src).count(), 1)

        # Re-run with a different result — old edges must be gone.
        self.monkeypatch.setattr(
            da.LLMAgent,
            "run",
            _reading_run(
                da.DependencyResult(internal=[], external_providers=[{"name": "Auth0"}])
            ),
        )
        da.infer_and_store(src)

        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 0)
        names = list(
            ExternalDependency.objects.filter(component__project=src).values_list(
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
            InfrastructureComponent.objects.filter(component__project=src).values_list(
                "name", "kind"
            )
        )
        self.assertIn(("Redis", "cache"), infra)
        self.assertIn(("PostgreSQL", "database"), infra)  # reclassified by backstop

        providers = list(
            ExternalDependency.objects.filter(
                component__project=src, direction=ExternalDependency.Direction.OUTBOUND
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

    # --- evidence gate -------------------------------------------------------

    def test_answer_without_reading_any_file_is_rejected_and_old_map_kept(self):
        _tenant, src, _api = self._setup(
            da.DependencyResult(internal=[{"target": "org/api"}])
        )
        da.infer_and_store(src)
        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 1)

        # A model that guesses without inspecting the repo (what a weak model
        # does when list_repo_files keeps coming back empty) must not be saved.
        self.monkeypatch.setattr(
            da.LLMAgent, "run", lambda self, **kw: da.DependencyResult()
        )
        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)
        self.assertIn("without reading any repository file", str(ctx.exception))

        # Previous edges survive; the task layer records the failure.
        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 1)
        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)

    def test_listing_only_without_reading_is_still_rejected(self):
        _tenant, src, _api = self._setup(da.DependencyResult())
        self.monkeypatch.setattr(
            da.LLMAgent, "run", _reading_run(da.DependencyResult(), paths=())
        )
        with self.assertRaises(RuntimeError):
            da.infer_and_store(src)

    def test_empty_repository_listing_is_rejected_with_a_connection_hint(self):
        _tenant, src, _api = self._setup(
            da.DependencyResult(), client=_fake_client(tree=(), files={})
        )
        self.monkeypatch.setattr(
            da.LLMAgent, "run", _reading_run(da.DependencyResult(), paths=())
        )
        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)
        self.assertIn("listing came back empty", str(ctx.exception))
        self.assertIn("connection", str(ctx.exception))


class ComponentRefResolutionTests(TestCase):
    """How an LLM-returned internal target maps onto the component roster."""

    def _roster(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        web = baker.make("app.Project", tenant=tenant, platform_connection=conn, name="web", full_path="org/web")
        mono = baker.make("app.Project", tenant=tenant, platform_connection=conn, name="mono", full_path="org/mono")
        gateway = baker.make(
            "app.Component", tenant=tenant, project=mono, path="apps/api-gateway", name="api-gateway"
        )
        auth = baker.make(
            "app.Component", tenant=tenant, project=mono, path="services/auth-service", name="auth-service"
        )
        # Roster as seen from a third project.
        other = baker.make("app.Project", tenant=tenant, platform_connection=conn, name="other", full_path="org/other")
        roster = da._component_roster(tenant, other)
        return web, mono, gateway, auth, roster

    def test_ref_forms_resolve_to_components(self):
        web, mono, gateway, auth, roster = self._roster()
        resolve = lambda t: da._resolve_internal_target(t, roster)

        self.assertEqual(resolve("org/web"), web.root_component.pk)  # root by full_path
        self.assertEqual(resolve("web"), web.root_component.pk)  # root by name
        self.assertEqual(resolve("org/mono#apps/api-gateway"), gateway.pk)  # canonical ref
        self.assertEqual(resolve("org/mono/apps/api-gateway"), gateway.pk)  # slash form
        self.assertEqual(resolve("auth-service"), auth.pk)  # unique component name
        self.assertEqual(resolve("org/mono"), mono.root_component.pk)  # bare monorepo → its root
        self.assertIsNone(resolve("org/nope"))
        self.assertIsNone(resolve(""))

    def test_roster_lines_name_components_by_ref(self):
        web, mono, gateway, auth, roster = self._roster()
        text = da._build_instructions(mono, roster)
        self.assertIn("ref: org/web  (name: web)", text)
        self.assertIn("ref: org/mono#apps/api-gateway  (repo: org/mono)", text)
