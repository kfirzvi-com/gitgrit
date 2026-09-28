"""``infer_and_store`` reads the repository's ``.gitgrit.yml`` first.

A valid map file replaces both LLM phases (zero model calls) and is saved the
same way an LLM answer is; a missing or invalid one falls back to the LLM with
the reason logged. The LLM role is only looked up for that fallback.
"""
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
from tests.application.test_dependency_agent import _fake_client, _model
from tests.support import MonkeyPatchMixin

MONO_TREE = (
    "README.md",
    "docker-compose.yml",
    "apps/api-gateway/package.json",
    "services/auth-service/pyproject.toml",
)

MAP_FILE = """\
version: 1
components:
  - path: apps/api-gateway
    name: api-gateway
    kind: service
    description: Public API.
    technologies: [Express]
    dependencies:
      internal:
        - target: "#services/auth-service"
          label: OAuth
        - target: org/api
      external_providers:
        - name: Stripe
          url: https://stripe.com
          label: payments
      external_consumers:
        - name: Partner portal
          label: webhooks
  - path: services/auth-service
    name: auth-service
    kind: service
    technologies: [FastAPI]
    dependencies:
      infrastructure:
        - name: PostgreSQL
          kind: database
          label: users DB
"""

# The same answer as MAP_FILE, given by the model.
LLM_ANSWER = dict(
    discovery=li.ComponentDiscovery(
        components=[
            {"path": "apps/api-gateway", "name": "api-gateway", "kind": "service", "description": "Public API."},
            {"path": "services/auth-service", "name": "auth-service", "kind": "service"},
        ]
    ),
    deps={
        "apps/api-gateway": li.DependencyResult(
            technologies=["Express"],
            internal=[{"target": "#services/auth-service", "label": "OAuth"}, {"target": "org/api"}],
            external_providers=[{"name": "Stripe", "url": "https://stripe.com", "label": "payments"}],
            external_consumers=[{"name": "Partner portal", "label": "webhooks"}],
        ),
        "services/auth-service": li.DependencyResult(
            technologies=["FastAPI"],
            infrastructure=[{"name": "PostgreSQL", "kind": "database", "label": "users DB"}],
        ),
    },
    paths=("docker-compose.yml",),
)

LOGGER = "app.application.architecture.refresh"


def _saved_map(project):
    """Everything the run wrote for ``project``, in comparable form."""
    return {
        "components": sorted(
            project.components.values_list("path", "name", "kind", "description", "technologies")
        ),
        "internal": sorted(
            ComponentDependency.objects.filter(source__project=project).values_list(
                "source__path", "target__project__full_path", "target__path", "label"
            )
        ),
        "externals": sorted(
            ExternalDependency.objects.filter(component__project=project).values_list(
                "component__path", "name", "direction", "url", "description"
            )
        ),
        "infrastructure": sorted(
            InfrastructureComponent.objects.filter(component__project=project).values_list(
                "component__path", "name", "kind", "description"
            )
        ),
    }


class MapFileFirstTests(MonkeyPatchMixin, TestCase):
    def _setup(self, *, map_file=None, tree=MONO_TREE, llm=True, **model):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant, platform="github")
        src = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn, name="mono", full_path="org/mono"
        )
        baker.make("app.Project", tenant=tenant, platform_connection=conn, name="api", full_path="org/api")
        self._files = {p: "{}" for p in tree}
        self._tree = list(tree)
        if map_file is not None:
            self._commit(map_file)
        self.monkeypatch.setattr(
            da,
            "resolve_llm_roles",
            lambda t: {"reasoning": {"model": "anthropic/claude", "base_url": "", "api_key": "k"}} if llm else {},
        )
        self.monkeypatch.setattr(
            "app.infrastructure.topology.snapshots.get_platform_client",
            lambda c: _fake_client(self._tree, self._files),
        )
        self._use_model(**model)
        return src

    def _commit(self, text):
        if ".gitgrit.yml" not in self._tree:
            self._tree.append(".gitgrit.yml")
        self._files[".gitgrit.yml"] = text

    def _use_model(self, **model):
        self.llm_calls = 0
        run = _model(**model)

        def counted(agent, **kw):
            self.llm_calls += 1
            return run(agent, **kw)

        self.monkeypatch.setattr(li.LLMAgent, "run", counted)

    def test_valid_file_builds_the_map_without_the_llm(self):
        src = self._setup(map_file=MAP_FILE)

        summary = da.infer_and_store(src)

        self.assertEqual(self.llm_calls, 0)
        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)
        self.assertEqual(src.deps_source, Project.DepsSource.FILE)
        self.assertEqual(src.deps_map, MAP_FILE)
        self.assertEqual(src.deps_evidence, [".gitgrit.yml"])
        self.assertEqual((summary.components, summary.internal, summary.infrastructure), (2, 2, 1))
        self.assertEqual((summary.providers, summary.consumers), (1, 1))
        saved = _saved_map(src)
        self.assertEqual(
            saved["internal"],
            [
                ("apps/api-gateway", "org/api", "", ""),
                ("apps/api-gateway", "org/mono", "services/auth-service", "OAuth"),
            ],
        )
        self.assertEqual(
            saved["infrastructure"], [("services/auth-service", "PostgreSQL", "database", "users DB")]
        )

    def test_file_and_llm_save_the_same_map_for_the_same_answer(self):
        src = self._setup(**LLM_ANSWER)
        da.infer_and_store(src)
        from_llm = _saved_map(src)
        src.refresh_from_db()
        self.assertEqual(src.deps_source, Project.DepsSource.LLM)
        self.assertGreater(self.llm_calls, 0)

        self._commit(MAP_FILE)
        self._use_model()
        da.infer_and_store(src)

        self.assertEqual(self.llm_calls, 0)
        self.assertEqual(_saved_map(src), from_llm)

    def test_stored_llm_answer_committed_as_the_file_reproduces_the_map(self):
        src = self._setup(**LLM_ANSWER)
        da.infer_and_store(src)
        from_llm = _saved_map(src)
        src.refresh_from_db()

        self._commit(src.deps_map)
        self._use_model()
        da.infer_and_store(src)

        self.assertEqual(self.llm_calls, 0)
        self.assertEqual(_saved_map(src), from_llm)
        src.refresh_from_db()
        self.assertEqual(src.deps_source, Project.DepsSource.FILE)

    def test_single_sub_component_file_keeps_its_edges_on_the_root(self):
        src = self._setup(
            map_file=(
                "version: 1\ncomponents:\n  - path: apps/api-gateway\n    dependencies:\n"
                "      internal:\n        - target: org/api\n"
            )
        )

        da.infer_and_store(src)

        self.assertEqual(list(src.components.values_list("path", "name")), [("", "mono")])
        self.assertEqual(ComponentDependency.objects.get(source__project=src).target.project.full_path, "org/api")

    def test_missing_file_runs_the_llm(self):
        src = self._setup(**LLM_ANSWER)

        with self.assertLogs(LOGGER, "INFO") as logs:
            da.infer_and_store(src)

        self.assertGreater(self.llm_calls, 0)
        self.assertIn("no .gitgrit.yml in the repository", "\n".join(logs.output))
        src.refresh_from_db()
        self.assertEqual(src.deps_source, Project.DepsSource.LLM)
        self.assertIn("path: apps/api-gateway", src.deps_map)
        self.assertEqual(src.components.count(), 2)

    def test_invalid_file_runs_the_llm_and_logs_why(self):
        cases = {
            "bad yaml": ("version: 1\ncomponents: [\n", "not valid YAML"),
            "bad kind": ("version: 1\ncomponents:\n  - path: ''\n    kind: daemon\n", "kind must be one of"),
            "missing dir": (
                "version: 1\ncomponents:\n  - path: apps/ghost\n",
                "path 'apps/ghost' is not a directory",
            ),
            "duplicate path": (
                "version: 1\ncomponents:\n  - path: apps/api-gateway\n  - path: ./apps/api-gateway/\n",
                "duplicate path 'apps/api-gateway'",
            ),
        }
        for name, (text, reason) in cases.items():
            with self.subTest(name):
                src = self._setup(map_file=text, **LLM_ANSWER)

                with self.assertLogs(LOGGER, "INFO") as logs:
                    da.infer_and_store(src)

                self.assertGreater(self.llm_calls, 0)
                self.assertIn(".gitgrit.yml is invalid", "\n".join(logs.output))
                self.assertIn(reason, "\n".join(logs.output))
                src.refresh_from_db()
                self.assertEqual(src.deps_source, Project.DepsSource.LLM)
                self.assertEqual(src.components.count(), 2)

    def test_valid_file_needs_no_llm_role(self):
        src = self._setup(map_file=MAP_FILE, llm=False)

        da.infer_and_store(src)

        src.refresh_from_db()
        self.assertEqual(src.deps_status, Project.DepsStatus.OK)
        self.assertEqual(src.deps_source, Project.DepsSource.FILE)

    def test_no_file_and_no_llm_role_raises_as_before(self):
        src = self._setup(llm=False)

        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)

        self.assertEqual(str(ctx.exception), str(self._role_error()))
        src.refresh_from_db()
        self.assertNotEqual(src.deps_status, Project.DepsStatus.OK)

    @staticmethod
    def _role_error():
        try:
            da.llm_inference_for(baker.make("app.Tenant"))
        except RuntimeError as exc:
            return exc

    def test_explicit_inference_skips_the_file(self):
        from app.domain.architecture.topology import ComponentDecl, Evidence, RepositoryTopology
        from app.infrastructure.topology.fake import FakeTopologyInference

        src = self._setup(map_file=MAP_FILE)
        fake = FakeTopologyInference(
            RepositoryTopology(
                components=(ComponentDecl("", "mono"),),
                evidence=Evidence(files_read=("README.md",)),
            )
        )

        da.infer_and_store(src, inference=fake)

        self.assertEqual(list(src.components.values_list("path", flat=True)), [""])
        src.refresh_from_db()
        self.assertEqual((src.deps_source, src.deps_map), ("", ""))

    def test_why_the_file_was_not_used_is_saved(self):
        cases = {
            "missing": (None, "no .gitgrit.yml in the repository"),
            "invalid": ("version: 1\ncomponents:\n  - path: apps/ghost\n", "path 'apps/ghost' is not a directory"),
        }
        for name, (text, reason) in cases.items():
            with self.subTest(name):
                src = self._setup(map_file=text, **LLM_ANSWER)

                with self.assertLogs(LOGGER, "WARNING") as logs:
                    da.infer_and_store(src)

                self.assertIn(reason, "\n".join(logs.output))
                src.refresh_from_db()
                self.assertIn(reason, src.deps_map_error)

        src = self._setup(map_file=MAP_FILE)
        da.infer_and_store(src)
        src.refresh_from_db()
        self.assertEqual(src.deps_map_error, "")

    def test_components_in_skipped_folders_are_allowed(self):
        tree = MONO_TREE + ("vendor/lib/setup.py", "tools/build/main.go")
        src = self._setup(
            tree=tree,
            map_file="version: 1\ncomponents:\n  - path: vendor/lib\n  - path: tools/build\n",
        )

        da.infer_and_store(src)

        self.assertEqual(self.llm_calls, 0)
        self.assertEqual(sorted(src.components.values_list("path", flat=True)), ["tools/build", "vendor/lib"])

    def test_read_error_on_the_file_runs_the_llm(self):
        import requests

        src = self._setup(map_file=MAP_FILE, **LLM_ANSWER)

        def get_file_content(full_path, path, ref):
            if path == ".gitgrit.yml":
                raise requests.HTTPError("502 Server Error: Bad Gateway")
            return self._files.get(path)

        client = _fake_client(self._tree, self._files)
        client.get_file_content = get_file_content
        self.monkeypatch.setattr("app.infrastructure.topology.snapshots.get_platform_client", lambda c: client)

        da.infer_and_store(src)

        self.assertGreater(self.llm_calls, 0)
        src.refresh_from_db()
        self.assertEqual(src.deps_source, Project.DepsSource.LLM)
        self.assertIn("502 Server Error", src.deps_map_error)

    def test_stored_llm_answer_uses_resolved_targets(self):
        answer = dict(LLM_ANSWER)
        answer["deps"] = {
            **LLM_ANSWER["deps"],
            "apps/api-gateway": li.DependencyResult(
                internal=[{"target": "auth-service"}, {"target": "api"}, {"target": "nowhere"}],
            ),
        }
        src = self._setup(**answer)
        da.infer_and_store(src)
        from_llm = _saved_map(src)
        src.refresh_from_db()

        self.assertIn('target: org/mono#services/auth-service', src.deps_map)
        self.assertIn("target: org/api", src.deps_map)
        self.assertNotIn("nowhere", src.deps_map)
        self._commit(src.deps_map)
        self._use_model()
        da.infer_and_store(src)

        self.assertEqual(self.llm_calls, 0)
        self.assertEqual(_saved_map(src), from_llm)

    def test_invalid_file_and_no_llm_role_keeps_the_file_reason(self):
        src = self._setup(map_file="version: 1\ncomponents:\n  - path: apps/ghost\n", llm=False)

        with self.assertRaises(RuntimeError) as ctx:
            da.infer_and_store(src)

        self.assertIn("path 'apps/ghost' is not a directory", str(ctx.exception))
        self.assertIn(str(self._role_error()), str(ctx.exception))
