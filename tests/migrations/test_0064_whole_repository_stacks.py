"""0064: a whole-repository project drops the stacks the first 0062 copied
onto it from its other components, and keeps the ones added since."""
from datetime import timedelta

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("app", "0063_retire_components")]
AFTER = [("app", "0064_whole_repository_stacks")]


class WholeRepositoryStacksTests(TransactionTestCase):
    def setUp(self):
        executor = MigrationExecutor(connection)
        executor.migrate(BEFORE)
        state = executor.loader.project_state(BEFORE[0]).apps
        old = executor.loader.project_state(("app", "0059_commit_score_ordered_by_run_time")).apps
        Tenant = old.get_model("app", "Tenant")
        tenant = Tenant.objects.create(name="Acme", slug="acme-0064-stacks")
        conn = old.get_model("app", "PlatformConnection").objects.create(
            tenant=tenant, platform="github", display_name="GitHub"
        )
        shop = old.get_model("app", "Project").objects.create(
            tenant=tenant, platform_connection=conn, platform="github", external_id="1",
            name="shop", full_path="acme/shop", web_url="https://example.test/acme/shop",
        )
        Stack = old.get_model("app", "Stack")
        self.platform, self.web, self.later = (
            Stack.objects.create(tenant=tenant, name=n) for n in ("Platform", "Web", "Later")
        )
        Component = old.get_model("app", "Component")
        root = Component.objects.create(tenant=tenant, project=shop, path="", name="shop")
        web = Component.objects.create(tenant=tenant, project=shop, path="apps/web", name="web")
        ComponentStack = old.get_model("app", "ComponentStack")
        ComponentStack.objects.create(component=root, stack=self.platform)
        ComponentStack.objects.create(component=web, stack=self.web)

        # What the first 0062 made (at migration time), and one added since.
        with connection.cursor() as c:
            c.execute("SELECT applied FROM django_migrations WHERE app='app' AND name='0062_copy_components_onto_projects'")
            applied = c.fetchone()[0]
        ProjectStack = state.get_model("app", "ProjectStack")
        ProjectStack.objects.filter(project_id=shop.pk).delete()
        for stack, at in ((self.platform, applied), (self.web, applied), (self.later, applied + timedelta(days=1))):
            row = ProjectStack.objects.create(project_id=shop.pk, stack_id=stack.pk)
            ProjectStack.objects.filter(pk=row.pk).update(created_at=at - timedelta(seconds=1) if at == applied else at)
        self.shop = shop

        executor.loader.build_graph()
        executor.migrate(AFTER)
        self.ProjectStack = executor.loader.project_state(AFTER[0]).apps.get_model("app", "ProjectStack")

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_keeps_the_root_components_stacks_and_later_ones(self):
        stacks = set(self.ProjectStack.objects.filter(project_id=self.shop.pk).values_list("stack_id", flat=True))
        self.assertEqual(stacks, {self.platform.pk, self.later.pk})
