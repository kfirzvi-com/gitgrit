"""0066 (phase 2): after the previous release served next to phase 1, its
component writes are copied onto projects, duplicates collapse, the
database enforces one external / infrastructure row per project and name,
and the component tables go."""
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

PHASE_1 = [("app", "0065_workspace_pins")]
PHASE_2 = [("app", "0066_drop_components")]
OLD_RELEASE = ("app", "0059_commit_score_ordered_by_run_time")


class DropComponentsTests(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(PHASE_1)
        old = executor.loader.project_state(OLD_RELEASE).apps  # the previous release's models
        new = executor.loader.project_state(PHASE_1[0]).apps
        Tenant = old.get_model("app", "Tenant")
        Project = old.get_model("app", "Project")
        Stack = old.get_model("app", "Stack")
        Component = old.get_model("app", "Component")

        tenant = Tenant.objects.create(name="Acme", slug="acme-0064")
        conn = old.get_model("app", "PlatformConnection").objects.create(
            tenant=tenant, platform="github", display_name="GitHub"
        )
        self.api = Project.objects.create(
            tenant=tenant, platform_connection=conn, platform="github", external_id="1",
            name="api", full_path="acme/api", web_url="https://example.test/acme/api",
        )
        self.web = Project.objects.create(
            tenant=tenant, platform_connection=conn, platform="github", external_id="2",
            name="web", full_path="acme/web", web_url="https://example.test/acme/web",
        )
        self.stack = Stack.objects.create(tenant=tenant, name="Core")
        api_root = Component.objects.create(tenant=tenant, project=self.api, path="", name="api")
        web_root = Component.objects.create(tenant=tenant, project=self.web, path="", name="web")

        # What the previous release wrote while phase 1 was live.
        old.get_model("app", "ComponentStack").objects.create(component=api_root, stack=self.stack)
        old.get_model("app", "ComponentDependency").objects.create(
            tenant=tenant, source=web_root, target=api_root, label="HTTPS"
        )
        old.get_model("app", "ExternalDependency").objects.create(
            tenant=tenant, component=api_root, name="Stripe", direction="outbound"
        )
        # The new release already wrote the same external by project.
        new.get_model("app", "ExternalDependency").objects.create(
            tenant_id=tenant.pk, project_id=self.api.pk, name="Stripe", direction="outbound"
        )

        executor.loader.build_graph()
        executor.migrate(PHASE_2)
        self.apps = executor.loader.project_state(PHASE_2[0]).apps
        self.tenant = tenant

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_what_the_previous_release_wrote_lands_on_projects(self):
        ProjectStack = self.apps.get_model("app", "ProjectStack")
        ProjectDependency = self.apps.get_model("app", "ProjectDependency")
        self.assertTrue(ProjectStack.objects.filter(project_id=self.api.pk, stack_id=self.stack.pk).exists())
        self.assertEqual(
            list(ProjectDependency.objects.values_list("source_id", "target_id", "label")),
            [(self.web.pk, self.api.pk, "HTTPS")],
        )

    def test_duplicates_collapse_and_the_database_enforces_it(self):
        External = self.apps.get_model("app", "ExternalDependency")
        self.assertEqual(External.objects.filter(project_id=self.api.pk).count(), 1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            External.objects.create(
                tenant_id=self.tenant.pk, project_id=self.api.pk, name="Stripe", direction="outbound"
            )

    def test_the_component_tables_are_gone(self):
        tables = connection.introspection.table_names()
        for table in ("components", "component_stacks", "component_dependencies"):
            self.assertNotIn(table, tables)
        columns = [c.name for c in connection.introspection.get_table_description(
            connection.cursor(), "external_dependencies"
        )]
        self.assertNotIn("component_id", columns)

    def test_it_migrates_back_to_phase_1(self):
        executor = MigrationExecutor(connection)
        executor.migrate(PHASE_1)
        self.assertIn("components", connection.introspection.table_names())
