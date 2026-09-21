"""``RefreshProjectTopology`` against a fixture inference and an in-memory
snapshot: no GitHub, no model. Pins the persistence rules — stable component
ids by path, membership inheritance on shape change, atomic edge replacement,
the evidence gate keeping the previous map, and re-queueing projects whose
edges pointed at a component that disappeared."""
from django.test import TestCase
from model_bakery import baker

from app.application.architecture.refresh import RefreshProjectTopology
from app.domain.architecture.topology import (
    INBOUND,
    OUTBOUND,
    ComponentDecl,
    Evidence,
    ExternalLink,
    InfrastructureResource,
    InternalDependency,
    RepositoryTopology,
    UngroundedTopology,
)
from app.domain.models import (
    Component,
    ComponentDependency,
    ExternalDependency,
    InfrastructureComponent,
    Project,
)
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


def _topology(components, internal=(), externals=(), infrastructure=(), files_read=("README.md",)):
    return RepositoryTopology(
        components=tuple(components),
        internal=tuple(internal),
        externals=tuple(externals),
        infrastructure=tuple(infrastructure),
        evidence=Evidence(tree_size=len(MONO_TREE), files_read=tuple(files_read)),
    )


ROOT = ComponentDecl("", "mono")
GATEWAY = ComponentDecl("apps/api-gateway", "api-gateway", kind="service", technologies=("Express",))
AUTH = ComponentDecl("services/auth-service", "auth-service", kind="service", technologies=("FastAPI",))
ORDERS = ComponentDecl("services/orders-service", "orders-service", kind="service", technologies=("Go",))


class RefreshProjectTopologyTests(TestCase):
    def setUp(self):
        self.tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=self.tenant, platform="github")
        self.mono = baker.make(
            "app.Project", tenant=self.tenant, platform_connection=conn, name="mono", full_path="org/mono"
        )
        self.web = baker.make(
            "app.Project", tenant=self.tenant, platform_connection=conn, name="web", full_path="org/web"
        )
        self.enqueued: list[str] = []

    def _run(self, topology, project=None, *, read_files=False):
        use_case = RefreshProjectTopology(
            inference=FakeTopologyInference(topology, read_files=read_files),
            snapshot_factory=lambda p: _MemorySnapshot(MONO_TREE),
            enqueue_refresh=self.enqueued.append,
        )
        return use_case.run(project or self.mono)

    def _paths(self, project=None):
        return dict((project or self.mono).components.values_list("path", "id"))

    # --- root-only ------------------------------------------------------------

    def test_root_only_result_keeps_the_root_component_and_its_id(self):
        root_id = self.mono.root_component.id
        summary = self._run(
            _topology(
                [ComponentDecl("", "whatever", technologies=("Django",))],
                internal=[InternalDependency("", "org/web", "REST")],
                externals=[ExternalLink("", "Stripe", OUTBOUND, "https://stripe.com", "payments")],
                infrastructure=[InfrastructureResource("", "PostgreSQL", "database")],
            )
        )

        self.assertEqual(self._paths(), {"": root_id})
        root = self.mono.root_component
        self.assertEqual(root.name, "mono")  # root keeps the project's name
        self.assertEqual(root.technologies, ["Django"])
        dep = ComponentDependency.objects.get(source=root)
        self.assertEqual(dep.target, self.web.root_component)
        self.assertEqual(ExternalDependency.objects.get(component=root).name, "Stripe")
        self.assertEqual(InfrastructureComponent.objects.get(component=root).kind, "database")
        self.assertEqual((summary.components, summary.internal, summary.providers), (1, 1, 1))
        self.mono.refresh_from_db()
        self.assertEqual(self.mono.deps_status, Project.DepsStatus.OK)
        self.assertEqual(self.mono.deps_evidence, ["README.md"])

    # --- discovery ------------------------------------------------------------

    def test_monorepo_discovery_creates_components_with_sibling_edges(self):
        summary = self._run(
            _topology(
                [GATEWAY, AUTH, ORDERS],
                internal=[
                    InternalDependency("apps/api-gateway", "#services/auth-service", "token validation"),
                    InternalDependency("apps/api-gateway", "org/mono#services/orders-service", "routing"),
                    InternalDependency("services/orders-service", "org/web", "callbacks"),
                    InternalDependency("services/orders-service", "org/nowhere"),
                ],
            )
        )

        self.assertEqual(
            set(self._paths()), {"apps/api-gateway", "services/auth-service", "services/orders-service"}
        )
        self.assertTrue(self.mono.is_monorepo)
        self.assertEqual(summary.created, ("apps/api-gateway", "services/auth-service", "services/orders-service"))
        self.assertEqual(summary.removed, ("",))
        self.assertEqual(summary.unresolved, ("org/nowhere",))
        edges = {
            (d.source.path, d.target.project.full_path, d.target.path, d.label)
            for d in ComponentDependency.objects.filter(source__project=self.mono).select_related(
                "source", "target__project"
            )
        }
        self.assertEqual(
            edges,
            {
                ("apps/api-gateway", "org/mono", "services/auth-service", "token validation"),
                ("apps/api-gateway", "org/mono", "services/orders-service", "routing"),
                ("services/orders-service", "org/web", "", "callbacks"),
            },
        )

    def test_shape_change_inherits_stack_memberships_from_the_root(self):
        storefront = baker.make("app.Stack", tenant=self.tenant, name="Storefront")
        self.mono.root_component.stacks.add(storefront)

        self._run(_topology([GATEWAY, AUTH]))

        for component in self.mono.components.all():
            self.assertEqual(list(component.stacks.all()), [storefront], component.path)
        self.assertEqual(storefront.components.count(), 2)

    def test_rerun_keeps_ids_and_memberships_for_unchanged_paths(self):
        self._run(_topology([GATEWAY, AUTH]))
        identity = baker.make("app.Stack", tenant=self.tenant, name="Identity")
        before = self._paths()
        Component.objects.get(pk=before["services/auth-service"]).stacks.add(identity)

        self._run(_topology([GATEWAY, ComponentDecl("services/auth-service", "auth (renamed)", kind="service")]))

        after = self._paths()
        self.assertEqual(after, before)
        auth = Component.objects.get(pk=after["services/auth-service"])
        self.assertEqual(auth.name, "auth (renamed)")
        self.assertEqual(list(auth.stacks.all()), [identity])

    def test_adding_a_component_does_not_spread_memberships(self):
        self._run(_topology([GATEWAY, AUTH]))
        identity = baker.make("app.Stack", tenant=self.tenant, name="Identity")
        Component.objects.get(project=self.mono, path="services/auth-service").stacks.add(identity)

        self._run(_topology([GATEWAY, AUTH, ORDERS]))

        orders = Component.objects.get(project=self.mono, path="services/orders-service")
        self.assertEqual(orders.stacks.count(), 0)

    def test_removed_component_requeues_projects_that_depended_on_it(self):
        self._run(_topology([GATEWAY, AUTH]))
        auth = Component.objects.get(project=self.mono, path="services/auth-service")
        ComponentDependency.objects.create(
            tenant=self.tenant, source=self.web.root_component, target=auth, label="OAuth"
        )

        with self.captureOnCommitCallbacks(execute=True):
            self._run(_topology([GATEWAY]))  # auth-service disappeared

        self.assertFalse(Component.objects.filter(pk=auth.pk).exists())
        self.assertEqual(self.enqueued, [str(self.web.pk)])
        self.assertEqual(ComponentDependency.objects.filter(source__project=self.web).count(), 0)

    def test_rerun_replaces_edges_atomically(self):
        self._run(_topology([ROOT], externals=[ExternalLink("", "Stripe", OUTBOUND)]))
        self._run(
            _topology(
                [ROOT],
                externals=[ExternalLink("", "Auth0", OUTBOUND), ExternalLink("", "Partner", INBOUND)],
            )
        )
        names = sorted(
            ExternalDependency.objects.filter(component__project=self.mono).values_list("name", flat=True)
        )
        self.assertEqual(names, ["Auth0", "Partner"])

    # --- evidence gate ---------------------------------------------------------

    def test_ungrounded_answer_is_rejected_and_the_previous_map_kept(self):
        self._run(_topology([ROOT], internal=[InternalDependency("", "org/web")]))
        self.assertEqual(ComponentDependency.objects.filter(source__project=self.mono).count(), 1)

        with self.assertRaises(UngroundedTopology):
            self._run(_topology([GATEWAY, AUTH], files_read=()))

        self.assertEqual(ComponentDependency.objects.filter(source__project=self.mono).count(), 1)
        self.assertEqual(set(self._paths()), {""})
        self.mono.refresh_from_db()
        self.assertEqual(self.mono.deps_status, Project.DepsStatus.OK)

    def test_fixture_inference_reads_evidence_from_the_snapshot(self):
        """``read_files=True`` (the CLI path) grounds the fixture in the real tree."""
        summary = self._run(_topology([ROOT], files_read=("README.md", "missing.txt")), read_files=True)
        self.mono.refresh_from_db()
        self.assertEqual(self.mono.deps_evidence, ["README.md"])
        self.assertEqual(summary.files_read, 1)
