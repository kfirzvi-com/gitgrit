"""``infer_and_store`` end to end with the LLM adapter, the model stubbed.

The adapter runs the agent once per project (its dependencies), plus a
discovery run for a whole-repository project (suggested projects); the stub
answers each ``run`` by the response model it is asked for, and inspects the
repository like a real model would so the evidence gate is satisfied.
"""
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
    every project, or a ``{root path: DependencyResult}`` map."""
    discovery = discovery or li.UnitDiscovery(units=[])
    deps = deps if deps is not None else li.DependencyResult()

    def run(self, **kw):
        toolbox = kw["toolbox"]
        if inspect:
            toolbox.list_repo_files("")
        if kw["response_model"] is li.UnitDiscovery:
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

    def test_writes_internal_and_external_edges_to_the_project(self):
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
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)
        self.assertIsNotNone(src.deps_analyzed_at)
        self.assertEqual(src.technologies, ["Express", "Next.js"])
        self.assertEqual(src.deps_evidence, ["package.json"])
        self.assertEqual(summary.suggestions, 0)

        pd = ProjectDependency.objects.get(source=src)
        self.assertEqual(pd.target, api)
        self.assertEqual(pd.label, "REST")
        provider = ExternalDependency.objects.get(project=src, direction=ExternalDependency.Direction.OUTBOUND)
        self.assertEqual((provider.name, provider.url), ("Stripe", "https://stripe.com"))
        consumer = ExternalDependency.objects.get(project=src, direction=ExternalDependency.Direction.INBOUND)
        self.assertEqual(consumer.name, "Partner API")

    def test_discovery_of_a_monorepo_suggests_its_projects(self):
        tree = (
            "README.md",
            "docker-compose.yml",
            "apps/api-gateway/package.json",
            "services/auth-service/pyproject.toml",
        )
        files = {p: "{}" for p in tree}
        _tenant, src, _api = self._setup(
            client=_fake_client(tree, files),
            discovery=li.UnitDiscovery(
                units=[
                    {"path": "apps/api-gateway", "name": "api-gateway", "kind": "service"},
                    {"path": "services/auth-service", "name": "auth-service", "kind": "service"},
                    {"path": "does/not/exist", "name": "ghost"},
                ]
            ),
            paths=("README.md",),
        )

        summary = da.infer_and_store(src)

        src.refresh_from_db()
        self.assertEqual(
            [(s["path"], s["name"], s["kind"]) for s in src.suggested_projects],
            [("apps/api-gateway", "api-gateway", "service"), ("services/auth-service", "auth-service", "service")],
        )
        self.assertEqual(summary.suggestions, 2)

    def test_a_rooted_project_is_scoped_to_its_directory_and_depends_on_its_neighbours(self):
        tree = ("README.md", "apps/api-gateway/package.json", "services/auth-service/pyproject.toml")
        files = {p: "{}" for p in tree}
        tenant, src, _api = self._setup(
            client=_fake_client(tree, files),
            deps={"apps/api-gateway": li.DependencyResult(
                technologies=["Express"], internal=[{"target": "#services/auth-service", "label": "OAuth"}]
            )},
            paths=("package.json",),
        )
        gateway = baker.make(
            "app.Project", tenant=tenant, platform_connection=src.platform_connection, name="web/apps/api-gateway",
            full_path="org/web", root_path="apps/api-gateway", external_id=src.external_id,
        )
        auth = baker.make(
            "app.Project", tenant=tenant, platform_connection=src.platform_connection, name="web/services/auth-service",
            full_path="org/web", root_path="services/auth-service", external_id=src.external_id,
        )

        da.infer_and_store(gateway)

        gateway.refresh_from_db()
        self.assertEqual(gateway.technologies, ["Express"])
        self.assertEqual(gateway.suggested_projects, [])
        self.assertEqual(
            [(d.target, d.label) for d in ProjectDependency.objects.filter(source=gateway)], [(auth, "OAuth")]
        )

    def test_unresolved_internal_target_is_skipped(self):
        _tenant, src, _api = self._setup(
            deps=li.DependencyResult(internal=[{"target": "org/does-not-exist"}])
        )

        summary = da.infer_and_store(src)

        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 0)
        self.assertEqual(summary.unresolved, ("org/does-not-exist",))
        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)

    def test_rerun_replaces_edges_atomically(self):
        _tenant, src, _api = self._setup(
            deps=li.DependencyResult(internal=[{"target": "org/api"}], external_providers=[{"name": "Stripe"}])
        )
        da.infer_and_store(src)
        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 1)
        self.assertEqual(ExternalDependency.objects.filter(project=src).count(), 1)

        self.monkeypatch.setattr(
            li.LLMAgent, "run", _model(deps=li.DependencyResult(external_providers=[{"name": "Auth0"}]))
        )
        da.infer_and_store(src)

        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 0)
        names = list(ExternalDependency.objects.filter(project=src).values_list("name", flat=True))
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

        infra = set(InfrastructureComponent.objects.filter(project=src).values_list("name", "kind"))
        self.assertEqual(infra, {("Redis", "cache"), ("PostgreSQL", "database")})
        providers = list(
            ExternalDependency.objects.filter(
                project=src, direction=ExternalDependency.Direction.OUTBOUND
            ).values_list("name", flat=True)
        )
        self.assertEqual(providers, ["Stripe"])

    def test_missing_reasoning_role_raises(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        src = baker.make("app.Project", tenant=tenant, platform_connection=conn, full_path="org/web")
        self.monkeypatch.setattr(da, "resolve_llm_roles", lambda t: {})

        with self.assertRaises(da.DependencyInferenceUnavailable) as ctx:
            da.infer_and_store(src)
        self.assertIn("No 'reasoning' LLM role configured", str(ctx.exception))

    # --- evidence gate -------------------------------------------------------

    def test_answer_without_reading_any_file_is_rejected_and_old_map_kept(self):
        _tenant, src, _api = self._setup(deps=li.DependencyResult(internal=[{"target": "org/api"}]))
        da.infer_and_store(src)
        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 1)

        # A model that guesses without inspecting the repo must not be saved.
        self.monkeypatch.setattr(li.LLMAgent, "run", _model(inspect=False))
        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)
        self.assertIn("without reading any repository file", str(ctx.exception))

        self.assertEqual(ProjectDependency.objects.filter(source=src).count(), 1)
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
    def test_roster_lines_name_projects_by_ref(self):
        from app.application.architecture.ports import InferenceContext
        from app.domain.architecture.resolve import RosterEntry

        roster = (
            RosterEntry("org/web", "", "web"),
            RosterEntry("org/mono", "apps/api-gateway", "api-gateway"),
        )
        ctx = InferenceContext(
            project_name="mono/services/auth", full_path="org/mono", root_path="services/auth",
            excluded_paths=("services/auth/admin",), roster=roster,
        )
        text = li._dependency_instructions(ctx)
        self.assertIn("ref: org/web  (name: web)", text)
        self.assertIn("ref: org/mono#apps/api-gateway  (repo: org/mono)", text)
        self.assertIn("Project to analyze: mono/services/auth at directory 'services/auth'", text)
        self.assertIn("leave them out: services/auth/admin", text)
