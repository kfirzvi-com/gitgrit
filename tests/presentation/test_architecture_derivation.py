from django.test import SimpleTestCase, TestCase
from model_bakery import baker

from app.application.naming import canonical_key
from app.domain.models import ExternalDependency
from app.presentation.architecture import (
    latest_scores_by_project,
    stack_graph,
    workspace_graph,
)


class WorkspaceGraphTests(TestCase):
    def test_derives_stack_edges_from_project_deps(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack_x = baker.make("app.Stack", tenant=tenant, name="X")
        stack_y = baker.make("app.Stack", tenant=tenant, name="Y")
        a = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        b = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        baker.make("app.ProjectStack", project=a, stack=stack_x)
        baker.make("app.ProjectStack", project=b, stack=stack_y)
        baker.make(
            "app.ProjectDependency", tenant=tenant, source=a, target=b, label="REST"
        )

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))
        deps = graph["dependencies"]

        self.assertEqual(len(deps), 1)
        self.assertEqual(deps[0]["source"], str(stack_x.id))
        self.assertEqual(deps[0]["target"], str(stack_y.id))
        self.assertEqual(deps[0]["label"], "REST")

    def test_same_stack_project_dep_yields_no_stack_edge(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="One")
        a = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        b = baker.make("app.Project", tenant=tenant, platform_connection=conn)
        baker.make("app.ProjectStack", project=a, stack=stack)
        baker.make("app.ProjectStack", project=b, stack=stack)
        baker.make("app.ProjectDependency", tenant=tenant, source=a, target=b)

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))

        # An intra-stack dep is not a stack→stack edge.
        self.assertEqual(graph["dependencies"], [])

    def test_stack_node_analyzing_flag(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            stacks=[stack],
            deps_status="running",
        )

        graph = workspace_graph(tenant, latest_scores_by_project(tenant))

        self.assertIs(graph["stacks"][0]["analyzing"], True)


class StackGraphTests(TestCase):
    def test_splits_external_by_direction(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        proj = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn, stacks=[stack]
        )
        baker.make(
            "app.ExternalDependency",
            tenant=tenant,
            project=proj,
            name="Stripe",
            direction=ExternalDependency.Direction.OUTBOUND,
        )
        baker.make(
            "app.ExternalDependency",
            tenant=tenant,
            project=proj,
            name="Partner API",
            direction=ExternalDependency.Direction.INBOUND,
        )

        g = stack_graph(stack, latest_scores_by_project(tenant))

        self.assertEqual([n["name"] for n in g["thirdparties"]], ["Stripe"])
        self.assertEqual([n["name"] for n in g["external_consumers"]], ["Partner API"])
        # Provider edge points project→external (thirdparty); consumer edge
        # external→project (public).
        kinds = {e["kind"] for e in g["edges"]}
        self.assertIn("thirdparty", kinds)
        self.assertIn("public", kinds)

    def test_project_tech_labels_merge_languages_and_inferred(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        baker.make(
            "app.Project",
            tenant=tenant,
            platform_connection=conn,
            stacks=[stack],
            languages=["TypeScript", "Go"],
            inferred_technologies=["Go", "Next.js", "Express"],  # "Go" dup → deduped
        )

        g = stack_graph(stack, latest_scores_by_project(tenant))
        techs = g["projects"][0]["technologies"]

        self.assertEqual(techs, ["TypeScript", "Go", "Next.js", "Express"])

    def test_includes_internal_infrastructure(self):
        tenant = baker.make("app.Tenant")
        conn = baker.make("app.PlatformConnection", tenant=tenant)
        stack = baker.make("app.Stack", tenant=tenant, name="S")
        proj = baker.make(
            "app.Project", tenant=tenant, platform_connection=conn, stacks=[stack]
        )
        baker.make(
            "app.InfrastructureComponent",
            tenant=tenant,
            project=proj,
            name="PostgreSQL",
            kind="database",
        )

        g = stack_graph(stack, latest_scores_by_project(tenant))

        self.assertEqual([n["name"] for n in g["infrastructure"]], ["PostgreSQL"])
        infra_id = g["infrastructure"][0]["id"]
        self.assertTrue(
            any(
                e["source"] == str(proj.id)
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
