"""``RefreshProjectTopology`` against a fixture inference and an in-memory
snapshot: no GitHub, no model. Pins the persistence rules — edges between
projects (also of one monorepo), suggested projects stored for the
whole-repository project only, its analysis leaving out the directories other
projects own, atomic edge replacement, and the evidence gate keeping the
previous map."""
from django.test import TestCase
from model_bakery import baker

from app.application.architecture.refresh import RefreshProjectTopology
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    Evidence,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    ProjectTopology,
    UngroundedTopology,
)
from app.domain.models import ExternalDependency, InfrastructureComponent, Project, ProjectDependency
from app.domain.projects import SuggestedProject
from app.infrastructure.topology.fake import FakeTopologyInference

MONO_TREE = [
    "README.md",
    "docker-compose.yml",
    "apps/api-gateway/package.json",
    "services/auth-service/pyproject.toml",
    "services/orders-service/go.mod",
]


class _MemorySnapshot:
    def __init__(self, tree, files=None):
        self._tree = list(tree)
        self._files = files or {p: "x" for p in tree}

    def list_files(self):
        return list(self._tree)

    def read_file(self, path):
        return self._files.get(path)


def _topology(internal=(), externals=(), infrastructure=(), suggestions=(), technologies=(), files_read=("README.md",)):
    return ProjectTopology(
        technologies=tuple(technologies),
        internal=tuple(internal),
        externals=tuple(externals),
        infrastructure=tuple(infrastructure),
        suggestions=tuple(suggestions),
        evidence=Evidence(tree_size=len(MONO_TREE), files_read=tuple(files_read)),
    )


GATEWAY = SuggestedProject("apps/api-gateway", "api-gateway", kind="service", technologies=("Express",))
AUTH = SuggestedProject("services/auth-service", "auth-service", kind="service")


class RefreshProjectTopologyTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        self.conn = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        self.mono = self._project("mono", "org/mono", "")
        self.web = self._project("web", "org/web", "", external_id="2")

    def _project(self, name, full_path, root_path, external_id="1"):
        return baker.make(
            "app.Project", tenant=self.tenant, platform_connection=self.conn, name=name,
            full_path=full_path, root_path=root_path, external_id=external_id,
        )

    def _run(self, topology, project=None, *, read_files=False):
        inference = FakeTopologyInference(topology, read_files=read_files)
        use_case = RefreshProjectTopology(
            inference=inference, snapshot_factory=lambda p: _MemorySnapshot(MONO_TREE)
        )
        self.inference = inference
        return use_case.run(project or self.mono)

    def test_edges_externals_infrastructure_and_tech_are_stored(self):
        summary = self._run(
            _topology(
                technologies=["Django"],
                internal=[InternalDependency("org/web", "REST")],
                externals=[ExternalLink("Stripe", OUTBOUND, "https://stripe.com", "payments")],
                infrastructure=[InfrastructureResource("PostgreSQL", "database")],
            )
        )

        self.mono.refresh_from_db()
        self.assertEqual(self.mono.technologies, ["Django"])
        self.assertEqual(ProjectDependency.objects.get(source=self.mono).target, self.web)
        self.assertEqual(ExternalDependency.objects.get(project=self.mono).name, "Stripe")
        self.assertEqual(InfrastructureComponent.objects.get(project=self.mono).kind, "database")
        self.assertEqual((summary.internal, summary.providers), (1, 1))
        self.assertEqual(self.mono.deps_status, Project.DepsStatus.OK)
        self.assertEqual(self.mono.deps_evidence, ["README.md"])

    def test_the_whole_repository_project_stores_its_suggestions(self):
        summary = self._run(_topology(suggestions=[GATEWAY, AUTH]))

        self.mono.refresh_from_db()
        self.assertEqual([s["path"] for s in self.mono.suggested_projects], [GATEWAY.path, AUTH.path])
        self.assertEqual(summary.suggestions, 2)
        self.assertTrue(self.inference.contexts[0].discover)

    def test_a_rooted_project_is_analysed_from_its_directory_and_suggests_nothing(self):
        gateway = self._project("mono/apps/api-gateway", "org/mono", "apps/api-gateway")
        self._run(_topology(suggestions=[AUTH]), project=gateway)

        context = self.inference.contexts[0]
        self.assertEqual((context.root_path, context.discover), ("apps/api-gateway", False))
        gateway.refresh_from_db()
        self.assertEqual(gateway.suggested_projects, [])

    def test_the_whole_repository_project_leaves_out_its_projects_directories(self):
        self._project("mono/apps/api-gateway", "org/mono", "apps/api-gateway")
        self._project("mono/services/auth-service", "org/mono", "services/auth-service")
        self._run(_topology())
        self.assertEqual(
            self.inference.contexts[0].excluded_paths, ("apps/api-gateway", "services/auth-service")
        )

    def test_projects_of_one_monorepo_depend_on_each_other(self):
        gateway = self._project("mono/apps/api-gateway", "org/mono", "apps/api-gateway")
        auth = self._project("mono/services/auth-service", "org/mono", "services/auth-service")
        summary = self._run(
            _topology(
                internal=[
                    InternalDependency("#services/auth-service", "token validation"),
                    InternalDependency("org/mono", "config"),
                    InternalDependency("#apps/api-gateway"),  # itself
                    InternalDependency("org/nowhere"),
                ]
            ),
            project=gateway,
        )
        edges = {
            (d.target_id, d.label) for d in ProjectDependency.objects.filter(source=gateway)
        }
        self.assertEqual(edges, {(auth.pk, "token validation"), (self.mono.pk, "config")})
        self.assertEqual(summary.unresolved, ("org/nowhere",))

    def test_rerun_replaces_edges_atomically(self):
        self._run(_topology(externals=[ExternalLink("Stripe", OUTBOUND)]))
        self._run(_topology(externals=[ExternalLink("Auth0", OUTBOUND), ExternalLink("Partner", INBOUND)]))
        names = sorted(ExternalDependency.objects.filter(project=self.mono).values_list("name", flat=True))
        self.assertEqual(names, ["Auth0", "Partner"])

    def test_ungrounded_answer_is_rejected_and_the_previous_map_kept(self):
        self._run(_topology(internal=[InternalDependency("org/web")], suggestions=[GATEWAY, AUTH]))
        self.assertEqual(ProjectDependency.objects.filter(source=self.mono).count(), 1)

        with self.assertRaises(UngroundedTopology):
            self._run(_topology(suggestions=[AUTH], files_read=()))

        self.assertEqual(ProjectDependency.objects.filter(source=self.mono).count(), 1)
        self.mono.refresh_from_db()
        self.assertEqual(len(self.mono.suggested_projects), 2)
        self.assertEqual(self.mono.deps_status, Project.DepsStatus.OK)

    def test_fixture_inference_reads_evidence_from_the_snapshot(self):
        """``read_files=True`` (the CLI path) grounds the fixture in the real tree."""
        summary = self._run(_topology(files_read=("README.md", "missing.txt")), read_files=True)
        self.mono.refresh_from_db()
        self.assertEqual(self.mono.deps_evidence, ["README.md"])
        self.assertEqual(summary.files_read, 1)

    def test_a_repository_fixture_gives_each_project_its_slice(self):
        repository = {
            "units": [{"path": "apps/api-gateway", "name": "api-gateway", "technologies": ["Express"]},
                      {"path": "services/auth-service", "name": "auth-service"}],
            "internal": [{"source_path": "apps/api-gateway", "target_ref": "{repo}#services/auth-service"}],
            "evidence": {"files_read": ["README.md"]},
        }
        gateway = self._project("mono/apps/api-gateway", "org/mono", "apps/api-gateway")
        auth = self._project("mono/services/auth-service", "org/mono", "services/auth-service")
        self._run(repository, project=gateway)
        gateway.refresh_from_db()
        self.assertEqual(gateway.technologies, ["Express"])
        self.assertEqual(ProjectDependency.objects.get(source=gateway).target, auth)
