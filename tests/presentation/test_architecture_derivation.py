from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.application.naming import canonical_key
from app.domain.models import ExternalDependency
from app.presentation.architecture import (
    stack_graph,
    workspace_graph,
)


def _project(tenant, conn, **kw):
    return baker.make("app.Project", tenant=tenant, platform_connection=conn, **kw)


def _in_repo(whole, path, **kw):
    """A project inside ``whole``'s repository (a monorepo), rooted at ``path``."""
    return baker.make(
        "app.Project",
        tenant=whole.tenant,
        platform_connection=whole.platform_connection,
        external_id=whole.external_id,
        full_path=whole.full_path,
        root_path=path,
        name=f"{whole.name}/{path}",
        **kw,
    )


class WorkspaceGraphTests(TestCase):
    def test_derives_stack_edges_from_project_deps(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack_x = baker.make("app.Stack", tenant=tenant, name="X")
        stack_y = baker.make("app.Stack", tenant=tenant, name="Y")
        a = _project(tenant, conn)
        b = _project(tenant, conn)
        a.stacks.add(stack_x)
        b.stacks.add(stack_y)
        baker.make(
            "app.ProjectDependency", tenant=tenant, source=a, target=b, label="REST"
        )

        graph = workspace_graph(tenant)
        deps = graph["dependencies"]

        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["source"], str(stack_x.id))
        self.assertEqual(deps[0]["target"], str(stack_y.id))
        self.assertEqual(deps[0]["label"], "REST")

    def test_same_stack_project_dep_yields_no_stack_edge(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="One")
        a = _project(tenant, conn)
        b = _project(tenant, conn)
        a.stacks.add(stack)
        b.stacks.add(stack)
        baker.make("app.ProjectDependency", tenant=tenant, source=a, target=b)

        graph = workspace_graph(tenant)

        # An intra-stack dep is not a stack→stack edge.
        self.assertEqual(graph["dependencies"], [])

    def test_monorepo_projects_in_different_stacks_yield_a_stack_edge(self):
        """Two projects of one repository, in two stacks, depending on each
        other, is a stack→stack edge — exactly like two repositories would be."""
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        storefront = baker.make("app.Stack", tenant=tenant, name="Storefront")
        identity = baker.make("app.Stack", tenant=tenant, name="Identity")
        mono = _project(tenant, conn, name="mono")
        gateway = _in_repo(mono, "apps/api-gateway")
        auth = _in_repo(mono, "services/auth-service")
        gateway.stacks.add(storefront)
        auth.stacks.add(identity)
        baker.make("app.ProjectDependency", tenant=tenant, source=gateway, target=auth)

        graph = workspace_graph(tenant)

        self.assertEqual(
            [(d["source"], d["target"]) for d in graph["dependencies"]],
            [(str(storefront.id), str(identity.id))],
        )

    def test_stack_node_counts_its_projects(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        mono = _project(tenant, conn, name="mono", deps_status="running")
        other = _in_repo(mono, "services/orders")
        mono.stacks.add(stack)
        other.stacks.add(stack)

        graph = workspace_graph(tenant)
        node = graph["stacks"][0]

        self.assertEqual(node["project_count"], 2)
        self.assertIs(node["analyzing"], True)


class StackGraphTests(TestCase):
    def test_splits_external_by_direction(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        root = _project(tenant, conn)
        root.stacks.add(stack)
        baker.make(
            "app.ExternalDependency",
            tenant=tenant,
            project=root,
            name="Stripe",
            direction=ExternalDependency.Direction.OUTBOUND,
        )
        baker.make(
            "app.ExternalDependency",
            tenant=tenant,
            project=root,
            name="Partner API",
            direction=ExternalDependency.Direction.INBOUND,
        )

        g = stack_graph(stack)

        self.assertEqual([n["name"] for n in g["thirdparties"]], ["Stripe"])
        self.assertEqual([n["name"] for n in g["external_consumers"]], ["Partner API"])
        # Provider edge points component→external (thirdparty); consumer edge
        # external→component (public).
        kinds = {e["kind"] for e in g["edges"]}
        self.assertIn("thirdparty", kinds)
        self.assertIn("public", kinds)

    def test_tech_labels_merge_languages_and_inferred(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        project = _project(
            tenant, conn, languages=["TypeScript", "Go"], technologies=["Go", "Next.js", "Express"]
        )  # "Go" dup → deduped
        project.stacks.add(stack)

        g = stack_graph(stack)
        techs = g["projects"][0]["technologies"]

        self.assertEqual(techs, ["TypeScript", "Go", "Next.js", "Express"])

    def test_a_project_inside_a_monorepo_carries_its_repository_and_path(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        mono = _project(tenant, conn, name="mono", full_path="org/mono", languages=["TypeScript", "Go", "Python"])
        auth = _in_repo(mono, "services/auth-service", languages=["Python"], technologies=["FastAPI"])
        auth.stacks.add(stack)

        g = stack_graph(stack)
        node = g["projects"][0]

        self.assertEqual(node["technologies"], ["Python", "FastAPI"])
        self.assertEqual(node["path"], "services/auth-service")
        self.assertEqual(node["repository"], "org/mono")
        self.assertIs(node["monorepo"], True)

    def test_boundary_nodes_are_projects_with_their_repository(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        orders_stack = baker.make("app.Stack", tenant=tenant, name="Orders")
        identity = baker.make("app.Stack", tenant=tenant, name="Identity")
        mono = _project(tenant, conn, name="mono", full_path="org/mono")
        orders = _in_repo(mono, "services/orders-service")
        auth = _in_repo(mono, "services/auth-service")
        orders.stacks.add(orders_stack)
        auth.stacks.add(identity)
        baker.make("app.ProjectDependency", tenant=tenant, source=orders, target=auth, label="OAuth")

        g = stack_graph(orders_stack)

        self.assertEqual(len(g["consuming"]), 1)
        node = g["consuming"][0]
        self.assertEqual(node["name"], "mono/services/auth-service")
        self.assertEqual(node["repository"], "org/mono")
        self.assertEqual(node["stack_name"], "Identity")
        self.assertEqual(g["edges"][0]["kind"], "consuming")

    def test_includes_internal_infrastructure(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        root = _project(tenant, conn)
        root.stacks.add(stack)
        baker.make(
            "app.InfrastructureComponent",
            tenant=tenant,
            project=root,
            name="PostgreSQL",
            kind="database",
        )

        g = stack_graph(stack)

        self.assertEqual([n["name"] for n in g["infrastructure"]], ["PostgreSQL"])
        infra_id = g["infrastructure"][0]["id"]
        self.assertTrue(
            any(
                e["source"] == str(root.id)
                and e["target"] == infra_id
                and e["kind"] == "internal"
                for e in g["edges"]
            )
        )


class CanonicalKeyTests(SimpleTestCase):
    def test_collapses_service_variants(self):
        self.assertEqual(canonical_key("Stripe"), "stripe")
        self.assertEqual(canonical_key("Stripe API"), "stripe")
        self.assertEqual(canonical_key("Auth0"), "auth0")
