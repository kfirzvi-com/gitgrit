"""``infer_and_store`` end to end with the LLM adapter, the model stubbed.

The adapter runs the agent twice per repository (discovery, then one
dependency run per component); the stub answers each ``run`` by the response
model it is asked for, and inspects the repository like a real model would so
the evidence gate is satisfied.
"""
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
from app.infrastructure.topology import llm_inference as li
from tests.support import MonkeyPatchMixin


def _fake_client(tree=("README.md", "package.json"), files=None):
    files = {"package.json": '{"name": "web"}'} if files is None else files
    return SimpleNamespace(
        get_tree=lambda full_path, ref: list(tree),
        get_file_content=lambda full_path, path, ref: files.get(path),
    )


def _model(*, discovery=None, deps=None, paths=("package.json",), inspect=True):
    """Stand in for ``LLMAgent.run``. ``deps`` is one ``DependencyResult`` for
    every component, or a ``{path: DependencyResult}`` map."""
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


class DependencyAgentTests(MonkeyPatchMixin, TestCase):
    def _setup(self, client=None, **model):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        src = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn, name="web", full_path="org/web"
        )
        api = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn, name="api", full_path="org/api"
        )
        # Avoid network + LLM: stub the role lookup, the platform client and the model.
        self.monkeypatch.setattr(
            da,
            "resolve_llm_roles",
            lambda t: {"reasoning": {"model": "anthropic/claude", "base_url": "", "api_key": "k"}},
        )
        self.monkeypatch.setattr(
            "app.infrastructure.topology.snapshots.get_platform_client",
            lambda c: client or _fake_client(),
        )
        self.monkeypatch.setattr(li.LLMAgent, "run", _model(**model))
        return tenant, src, api

    def test_writes_internal_and_external_edges_to_the_root_component(self):
        _tenant, src, api = self._setup(
            deps=li.DependencyResult(
                technologies=["Express", "Express", "Next.js"],  # dup → deduped
                internal=[{"target": "org/api", "label": "REST"}],
                external_providers=[{"name": "Stripe", "url": "https://stripe.com", "label": "payments"}],
                external_consumers=[{"name": "Partner API", "label": "public"}],
            )
        )

        summary = da.infer_and_store(src)

        src.refresh_from_db()
        root = src.root_component
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)
        self.assertIsNotNone(src.deps_analyzed_at)
        self.assertEqual(root.technologies, ["Express", "Next.js"])
        self.assertEqual(src.deps_evidence, ["package.json"])
        self.assertEqual(summary.components, 1)

        pd = ComponentDependency.objects.get(source=root)
        self.assertEqual(pd.target, api.root_component)
        self.assertEqual(pd.label, "REST")
        provider = ExternalDependency.objects.get(component=root, direction=ExternalDependency.Direction.OUTBOUND)
        self.assertEqual((provider.name, provider.url), ("Stripe", "https://stripe.com"))
        consumer = ExternalDependency.objects.get(component=root, direction=ExternalDependency.Direction.INBOUND)
        self.assertEqual(consumer.name, "Partner API")

    def test_discovery_of_a_monorepo_creates_components_and_sibling_edges(self):
        tree = (
            "README.md",
            "docker-compose.yml",
            "apps/api-gateway/package.json",
            "services/auth-service/pyproject.toml",
        )
        files = {p: "{}" for p in tree}
        _tenant, src, api = self._setup(
            client=_fake_client(tree, files),
            discovery=li.ComponentDiscovery(
                components=[
                    {"path": "apps/api-gateway", "name": "api-gateway", "kind": "service"},
                    {"path": "services/auth-service", "name": "auth-service", "kind": "service"},
                    {"path": "does/not/exist", "name": "ghost"},
                ]
            ),
            deps={
                "apps/api-gateway": li.DependencyResult(
                    technologies=["Express"],
                    internal=[{"target": "org/web#services/auth-service", "label": "OAuth"}, {"target": "org/api"}],
                ),
                "services/auth-service": li.DependencyResult(
                    technologies=["FastAPI"], infrastructure=[{"name": "PostgreSQL", "kind": "database"}]
                ),
            },
            paths=("package.json",),
        )

        summary = da.infer_and_store(src)

        paths = dict(src.components.values_list("path", "name"))
        self.assertEqual(paths, {"apps/api-gateway": "api-gateway", "services/auth-service": "auth-service"})
        self.assertEqual(summary.components, 2)
        gateway = src.components.get(path="apps/api-gateway")
        auth = src.components.get(path="services/auth-service")
        self.assertEqual(gateway.technologies, ["Express"])
        targets = {(d.target.pk, d.label) for d in ComponentDependency.objects.filter(source=gateway)}
        self.assertEqual(targets, {(auth.pk, "OAuth"), (api.root_component.pk, "")})
        self.assertEqual(InfrastructureComponent.objects.get(component=auth).name, "PostgreSQL")

    def test_unresolved_internal_target_is_skipped(self):
        _tenant, src, _api = self._setup(
            deps=li.DependencyResult(internal=[{"target": "org/does-not-exist"}])
        )

        summary = da.infer_and_store(src)

        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 0)
        self.assertEqual(summary.unresolved, ("org/does-not-exist",))
        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)

    def test_rerun_replaces_edges_atomically(self):
        _tenant, src, _api = self._setup(
            deps=li.DependencyResult(internal=[{"target": "org/api"}], external_providers=[{"name": "Stripe"}])
        )
        da.infer_and_store(src)
        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 1)
        self.assertEqual(ExternalDependency.objects.filter(component__project=src).count(), 1)

        self.monkeypatch.setattr(
            li.LLMAgent, "run", _model(deps=li.DependencyResult(external_providers=[{"name": "Auth0"}]))
        )
        da.infer_and_store(src)

        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 0)
        names = list(ExternalDependency.objects.filter(component__project=src).values_list("name", flat=True))
        self.assertEqual(names, ["Auth0"])

    def test_infrastructure_backstop_and_external_dedup(self):
        _tenant, src, _api = self._setup(
            deps=li.DependencyResult(
                infrastructure=[{"name": "Redis", "kind": "cache"}],
                external_providers=[
                    {"name": "Stripe"},
                    {"name": "Stripe API"},  # same service → deduped
                    {"name": "PostgreSQL"},  # datastore → backstop moves to infra
                ],
            )
        )

        da.infer_and_store(src)

        infra = set(InfrastructureComponent.objects.filter(component__project=src).values_list("name", "kind"))
        self.assertEqual(infra, {("Redis", "cache"), ("PostgreSQL", "database")})
        providers = list(
            ExternalDependency.objects.filter(
                component__project=src, direction=ExternalDependency.Direction.OUTBOUND
            ).values_list("name", flat=True)
        )
        self.assertEqual(providers, ["Stripe"])

    def test_missing_reasoning_role_raises(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        src = baker.make("app.Project", tenant=tenant, platform_connection=conn, full_path="org/web")
        self.monkeypatch.setattr(da, "resolve_llm_roles", lambda t: {})

        with self.assertRaises(RuntimeError):
            da.infer_and_store(src)

    # --- evidence gate -------------------------------------------------------

    def test_answer_without_reading_any_file_is_rejected_and_old_map_kept(self):
        _tenant, src, _api = self._setup(deps=li.DependencyResult(internal=[{"target": "org/api"}]))
        da.infer_and_store(src)
        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 1)

        # A model that guesses without inspecting the repo must not be saved.
        self.monkeypatch.setattr(li.LLMAgent, "run", _model(inspect=False))
        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)
        self.assertIn("without reading any repository file", str(ctx.exception))

        self.assertEqual(ComponentDependency.objects.filter(source__project=src).count(), 1)
        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)

    def test_listing_only_without_reading_is_still_rejected(self):
        _tenant, src, _api = self._setup(paths=())
        with self.assertRaises(RuntimeError):
            da.infer_and_store(src)

    def test_empty_repository_listing_is_rejected_with_a_connection_hint(self):
        _tenant, src, _api = self._setup(client=_fake_client(tree=(), files={}), paths=())
        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)
        self.assertIn("listing came back empty", str(ctx.exception))
        self.assertIn("connection", str(ctx.exception))


class RosterInstructionsTests(TestCase):
    def test_roster_lines_name_components_by_ref(self):
        from app.application.architecture.ports import InferenceContext
        from app.domain.architecture.resolve import RosterEntry
        from app.domain.architecture.topology import ComponentDecl

        roster = (
            RosterEntry("org/web", "", "web"),
            RosterEntry("org/mono", "apps/api-gateway", "api-gateway"),
        )
        ctx = InferenceContext(project_name="mono", full_path="org/mono", roster=roster)
        text = li._dependency_instructions(ctx, ComponentDecl("services/auth", "auth"), roster)
        self.assertIn("ref: org/web  (name: web)", text)
        self.assertIn("ref: org/mono#apps/api-gateway  (repo: org/mono)", text)
        self.assertIn("Component to analyze: auth at directory 'services/auth'", text)
