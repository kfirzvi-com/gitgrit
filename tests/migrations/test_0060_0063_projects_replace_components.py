"""0060–0063: projects take over from components with zero downtime.

``migrate`` runs before the new release goes live, so for a while the
previous release (schema 0059: components, no root paths) serves against the
migrated database next to the new one. These tests migrate a database that
holds components forward, check the copy, then act as each release:

* the previous release, through its own model state (0059), must still read
  and write everything it knows;
* the new release must be able to delete projects, stacks and workspaces
  although component rows still point at them.

Going back to 0060 must work too.
"""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("app", "0060_project_root_path")]
OLD_RELEASE = ("app", "0059_commit_score_ordered_by_run_time")
LATEST = [("app", "0063_retire_components")]


class ProjectsReplaceComponentsTests(TransactionTestCase):

    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(BEFORE)
        old = self.executor.loader.project_state(BEFORE[0]).apps
        Tenant = old.get_model("app", "Tenant")
        Connection = old.get_model("app", "PlatformConnection")
        Project = old.get_model("app", "Project")
        Stack = old.get_model("app", "Stack")
        Component = old.get_model("app", "Component")
        ComponentStack = old.get_model("app", "ComponentStack")
        ComponentDependency = old.get_model("app", "ComponentDependency")
        External = old.get_model("app", "ExternalDependency")

        self.tenant = Tenant.objects.create(name="Acme", slug="acme")
        conn = Connection.objects.create(tenant=self.tenant, platform="github", display_name="GitHub")
        self.shop = Project.objects.create(
            tenant=self.tenant, platform_connection=conn, platform="github", external_id="1",
            name="shop", full_path="acme/shop", web_url="https://example.test/acme/shop",
        )
        self.billing = Project.objects.create(
            tenant=self.tenant, platform_connection=conn, platform="github", external_id="2",
            name="billing", full_path="acme/billing", web_url="https://example.test/acme/billing",
        )
        self.web_stack = Stack.objects.create(tenant=self.tenant, name="Web")
        self.pay_stack = Stack.objects.create(tenant=self.tenant, name="Payments")
        shop_root = Component.objects.create(
            tenant=self.tenant, project=self.shop, path="", name="shop", kind="service", technologies=["Go"]
        )
        web = Component.objects.create(
            tenant=self.tenant, project=self.shop, path="apps/web", name="web", kind="frontend",
            description="Storefront", technologies=["Next.js"],
        )
        billing_root = Component.objects.create(tenant=self.tenant, project=self.billing, path="", name="billing")
        ComponentStack.objects.create(component=web, stack=self.web_stack)
        ComponentStack.objects.create(component=billing_root, stack=self.pay_stack)
        ComponentDependency.objects.create(tenant=self.tenant, source=web, target=billing_root, label="HTTPS")
        ComponentDependency.objects.create(tenant=self.tenant, source=web, target=shop_root, label="same repo")
        External.objects.create(tenant=self.tenant, component=web, name="Stripe", direction="outbound")

        self.executor.loader.build_graph()
        self.executor.migrate(LATEST)
        self.new = self.executor.loader.project_state(LATEST[0]).apps
        self.previous = self.executor.loader.project_state(OLD_RELEASE).apps

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    # --- the copy ------------------------------------------------------------

    def test_component_data_moves_onto_projects(self):
        Project = self.new.get_model("app", "Project")
        ProjectStack = self.new.get_model("app", "ProjectStack")
        ProjectDependency = self.new.get_model("app", "ProjectDependency")
        External = self.new.get_model("app", "ExternalDependency")
        shop = Project.objects.get(pk=self.shop.pk)

        self.assertEqual((shop.kind, shop.technologies), ("service", ["Go"]))
        [suggestion] = shop.suggested_projects
        self.assertEqual(
            (suggestion["path"], suggestion["kind"], suggestion["stack_ids"]),
            ("apps/web", "frontend", [str(self.web_stack.pk)]),
        )
        self.assertEqual(
            set(ProjectStack.objects.values_list("project_id", "stack_id")),
            {(self.shop.pk, self.web_stack.pk), (self.billing.pk, self.pay_stack.pk)},
        )
        # The edge inside the shop repository collapses until apps/web is a project.
        self.assertEqual(
            list(ProjectDependency.objects.values_list("source_id", "target_id", "label")),
            [(self.shop.pk, self.billing.pk, "HTTPS")],
        )
        self.assertEqual(External.objects.get().project_id, self.shop.pk)

    # --- the previous release, still serving ---------------------------------

    def test_the_previous_release_still_adds_projects_and_components(self):
        Tenant = self.previous.get_model("app", "Tenant")
        Connection = self.previous.get_model("app", "PlatformConnection")
        Project = self.previous.get_model("app", "Project")
        Stack = self.previous.get_model("app", "Stack")
        Component = self.previous.get_model("app", "Component")
        ComponentStack = self.previous.get_model("app", "ComponentStack")
        External = self.previous.get_model("app", "ExternalDependency")
        tenant = Tenant.objects.get(pk=self.tenant.pk)

        project = Project.objects.create(
            tenant=tenant, platform_connection=Connection.objects.get(), platform="github",
            external_id="3", name="search", full_path="acme/search", web_url="https://example.test/acme/search",
        )
        root = Component.objects.create(tenant=tenant, project=project, path="", name="search")
        ComponentStack.objects.create(component=root, stack=Stack.objects.get(pk=self.web_stack.pk))
        External.objects.create(tenant=tenant, component=root, name="Algolia", direction="outbound")

        # The new release sees the project with the columns' defaults.
        new_project = self.new.get_model("app", "Project").objects.get(pk=project.pk)
        self.assertEqual(
            (new_project.root_path, new_project.kind, new_project.technologies, new_project.suggested_projects),
            ("", "other", [], []),
        )

    def test_the_previous_release_still_reads_and_deletes(self):
        Project = self.previous.get_model("app", "Project")
        Component = self.previous.get_model("app", "Component")

        self.assertEqual(
            sorted(Component.objects.filter(project__full_path="acme/shop").values_list("path", flat=True)),
            ["", "apps/web"],
        )
        Project.objects.get(pk=self.shop.pk).delete()  # its Python cascade clears the components first
        self.previous.get_model("app", "Stack").objects.filter(pk=self.pay_stack.pk).delete()

        self.assertFalse(Component.objects.filter(project_id=self.shop.pk).exists())
        # The tables it doesn't know were cleared by the database.
        ProjectStack = self.new.get_model("app", "ProjectStack")
        self.assertFalse(ProjectStack.objects.filter(project_id=self.shop.pk).exists())
        self.assertFalse(ProjectStack.objects.filter(stack_id=self.pay_stack.pk).exists())

    # --- the new release ------------------------------------------------------

    def test_the_new_release_deletes_although_components_point_at_it(self):
        Project = self.new.get_model("app", "Project")
        Stack = self.new.get_model("app", "Stack")
        Tenant = self.new.get_model("app", "Tenant")

        Project.objects.filter(pk=self.shop.pk).delete()
        Stack.objects.filter(pk=self.pay_stack.pk).delete()
        Tenant.objects.filter(pk=self.tenant.pk).delete()

        self.assertFalse(Tenant.objects.exists())

    def test_the_new_release_writes_externals_by_project_only(self):
        External = self.new.get_model("app", "ExternalDependency")
        External.objects.create(tenant_id=self.tenant.pk, project_id=self.billing.pk, name="Auth0", direction="outbound")
        self.assertEqual(External.objects.filter(project_id=self.billing.pk).count(), 1)

    # --- rolling back -----------------------------------------------------------

    def test_it_migrates_back(self):
        self.executor.loader.build_graph()
        self.executor.migrate(BEFORE)
        Component = self.executor.loader.project_state(BEFORE[0]).apps.get_model("app", "Component")
        self.assertEqual(Component.objects.filter(tenant_id=self.tenant.pk).count(), 3)
