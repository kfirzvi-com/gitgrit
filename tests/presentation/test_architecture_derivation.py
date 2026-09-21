from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.application.naming import canonical_key
from app.domain.models import ExternalDependency
from app.presentation.architecture import (
    latest_scores_by_project,
    stack_graph,
    workspace_graph,
)


def _project(tenant, conn, **kw):
    """A project and its root component (created by the post_save signal)."""
    project = baker.make("app.Project", tenant=tenant, platform_connection=conn, **kw)
    return project, project.root_component


def _component(project, path, name=None, **kw):
    return baker.make(
        "app.Component",
        tenant=project.tenant,
        project=project,
        path=path,
        name=name or path.rsplit("/", 1)[-1],
        **kw,
    )


class WorkspaceGraphTests(TestCase):
    def test_derives_stack_edges_from_component_deps(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack_x = baker.make("app.Stack", tenant=tenant, name="X")
        stack_y = baker.make("app.Stack", tenant=tenant, name="Y")
        _, a = _project(tenant, conn)
        _, b = _project(tenant, conn)
        a.stacks.add(stack_x)
        b.stacks.add(stack_y)
        baker.make(
            "app.ComponentDependency", tenant=tenant, source=a, target=b, label="REST"
        )

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))
        deps = graph["dependencies"]

        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["source"], str(stack_x.id))
        self.assertEqual(deps[0]["target"], str(stack_y.id))
        self.assertEqual(deps[0]["label"], "REST")

    def test_same_stack_component_dep_yields_no_stack_edge(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="One")
        _, a = _project(tenant, conn)
        _, b = _project(tenant, conn)
        a.stacks.add(stack)
        b.stacks.add(stack)
        baker.make("app.ComponentDependency", tenant=tenant, source=a, target=b)

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))

        # An intra-stack dep is not a stack→stack edge.
        self.assertEqual(graph["dependencies"], [])

    def test_monorepo_components_in_different_stacks_yield_a_stack_edge(self):
        """Two components of one repository, in two stacks, depending on each
        other, is a stack→stack edge — exactly like two repositories would be."""
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        storefront = baker.make("app.Stack", tenant=tenant, name="Storefront")
        identity = baker.make("app.Stack", tenant=tenant, name="Identity")
        mono, _root = _project(tenant, conn, name="mono")
        gateway = _component(mono, "apps/api-gateway")
        auth = _component(mono, "services/auth-service")
        gateway.stacks.add(storefront)
        auth.stacks.add(identity)
        baker.make("app.ComponentDependency", tenant=tenant, source=gateway, target=auth)

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))

        self.assertEqual(
            [(d["source"], d["target"]) for d in graph["dependencies"]],
            [(str(storefront.id), str(identity.id))],
        )

    def test_stack_node_counts_components_and_distinct_projects(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        mono, root = _project(tenant, conn, deps_status="running")
        other = _component(mono, "services/orders")
        root.stacks.add(stack)
        other.stacks.add(stack)

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))
        node = graph["stacks"][0]

        self.assertEqual(node["component_count"], 2)
        self.assertEqual(node["project_count"], 1)
        self.assertIs(node["analyzing"], True)


class StackGraphTests(TestCase):
    def test_splits_external_by_direction(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        _, root = _project(tenant, conn)
        root.stacks.add(stack)
        baker.make(
            "app.ExternalDependency",
            tenant=tenant,
            component=root,
            name="Stripe",
            direction=ExternalDependency.Direction.OUTBOUND,
        )
        baker.make(
            "app.ExternalDependency",
            tenant=tenant,
            component=root,
            name="Partner API",
            direction=ExternalDependency.Direction.INBOUND,
        )

        g = stack_graph(stack, latest_scores_by_project(tenant))

        self.assertEqual([n["name"] for n in g["thirdparties"]], ["Stripe"])
        self.assertEqual([n["name"] for n in g["external_consumers"]], ["Partner API"])
        # Provider edge points component→external (thirdparty); consumer edge
        # external→component (public).
        kinds = {e["kind"] for e in g["edges"]}
        self.assertIn("thirdparty", kinds)
        self.assertIn("public", kinds)

    def test_root_component_tech_labels_merge_languages_and_inferred(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        _, root = _project(tenant, conn, languages=["TypeScript", "Go"])
        root.technologies = ["Go", "Next.js", "Express"]  # "Go" dup → deduped
        root.save()
        root.stacks.add(stack)

        g = stack_graph(stack, latest_scores_by_project(tenant))
        techs = g["components"][0]["technologies"]

        self.assertEqual(techs, ["TypeScript", "Go", "Next.js", "Express"])

    def test_sub_component_tech_labels_skip_repo_wide_languages(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        mono, _root = _project(tenant, conn, name="mono", languages=["TypeScript", "Go", "Python"])
        auth = _component(mono, "services/auth-service", technologies=["FastAPI"])
        auth.stacks.add(stack)

        g = stack_graph(stack, latest_scores_by_project(tenant))
        node = g["components"][0]

        self.assertEqual(node["technologies"], ["FastAPI"])
        self.assertEqual(node["path"], "services/auth-service")
        self.assertEqual(node["project_name"], "mono")
        self.assertIs(node["monorepo"], True)

    def test_boundary_nodes_are_components_with_their_repository(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        orders_stack = baker.make("app.Stack", tenant=tenant, name="Orders")
        identity = baker.make("app.Stack", tenant=tenant, name="Identity")
        mono, _root = _project(tenant, conn, name="mono")
        orders = _component(mono, "services/orders-service")
        auth = _component(mono, "services/auth-service")
        orders.stacks.add(orders_stack)
        auth.stacks.add(identity)
        baker.make("app.ComponentDependency", tenant=tenant, source=orders, target=auth, label="OAuth")

        g = stack_graph(orders_stack, latest_scores_by_project(tenant))

        self.assertEqual(len(g["consuming"]), 1)
        node = g["consuming"][0]
        self.assertEqual(node["name"], "auth-service")
        self.assertEqual(node["project_name"], "mono")
        self.assertEqual(node["stack_name"], "Identity")
        self.assertEqual(g["edges"][0]["kind"], "consuming")

    def test_includes_internal_infrastructure(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        _, root = _project(tenant, conn)
        root.stacks.add(stack)
        baker.make(
            "app.InfrastructureComponent",
            tenant=tenant,
            component=root,
            name="PostgreSQL",
            kind="database",
        )

        g = stack_graph(stack, latest_scores_by_project(tenant))

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
