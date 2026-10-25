"""0054 run for real, on rows, the way a deploy runs it (its own
transactions, not a test's): rescoring commit_scores and then adding its
constraint must not trip Postgres's "pending trigger events"."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("app", "0053_commit_scores")]
AFTER = [("app", "0054_commit_score_outcomes")]


class MigrateWithDataTests(TransactionTestCase):
    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.executor.migrate(BEFORE)
        apps = self.executor.loader.project_state(BEFORE).apps
        Tenant = apps.get_model("app", "Tenant")
        Project = apps.get_model("app", "Project")
        Standard = apps.get_model("app", "Standard")
        CommitCheck = apps.get_model("app", "CommitCheck")
        StandardExecution = apps.get_model("app", "StandardExecution")
        CommitScore = apps.get_model("app", "CommitScore")

        PlatformConnection = apps.get_model("app", "PlatformConnection")
        tenant = Tenant.objects.create(name="Acme", slug="acme")
        connection_row = PlatformConnection.objects.create(tenant=tenant, platform="github", display_name="Acme")
        project = Project.objects.create(
            tenant=tenant, platform_connection=connection_row, platform="github", external_id="1",
            name="api", full_path="acme/api", default_branch="main",
        )
        lint = Standard.objects.create(tenant=tenant, name="Lint")
        docs = Standard.objects.create(tenant=tenant, name="Docs")
        check = CommitCheck.objects.create(
            project=project, branch="main", commit_sha="a" * 40, event_type="push",
            expected_standard_ids=[str(lint.pk), str(docs.pk)],
        )
        for standard, status in ((lint, "failed"), (docs, "error")):
            StandardExecution.objects.create(
                project=project, standard=standard, standard_name=standard.name, commit_check=check,
                status=status, score=0, importance="required",
            )
        # Saved under the old rules: failed, and stored as 0.
        CommitScore.objects.create(
            project=project, commit_check=check, branch="main", commit_sha="a" * 40,
            ordered_at=check.created_at, value=0, failed=True, reason="Lint failing",
        )
        self.check_id = check.pk
        # A finished check that never saved a score: 0054 inserts one, which
        # is what leaves Postgres trigger events pending before the
        # constraint is added.
        unsaved = CommitCheck.objects.create(
            project=project, branch="main", commit_sha="b" * 40, event_type="push",
            expected_standard_ids=[str(lint.pk)],
        )
        StandardExecution.objects.create(
            project=project, standard=lint, standard_name="Lint", commit_check=unsaved,
            status="passed", score=100, importance="major",
        )
        self.unsaved_id = unsaved.pk

    def tearDown(self):
        # Leave the schema at the newest migration for the next tests.
        MigrationExecutor(connection).migrate(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_it_rescores_and_adds_the_constraint(self):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(AFTER)

        apps = executor.loader.project_state(AFTER).apps
        score = apps.get_model("app", "CommitScore").objects.get(commit_check_id=self.check_id)
        assert (score.value, score.failed, score.reason) == (None, False, "Docs errored")
        assert apps.get_model("app", "Tenant").objects.get().score_display == "letters"
        saved = apps.get_model("app", "CommitScore").objects.get(commit_check_id=self.unsaved_id)
        assert (saved.value, saved.failed) == (100, False)


class MigrateFromProductionTests(TransactionTestCase):
    """Production is at 0051: one deploy runs 0052, 0053 and 0054 on its
    checks and runs, which have no commit scores yet."""

    FROM = [("app", "0051_workspace_invitations")]

    def tearDown(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_it_migrates_runs_and_checks_into_commit_scores(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.FROM)
        apps = executor.loader.project_state(self.FROM).apps
        Tenant = apps.get_model("app", "Tenant")
        PlatformConnection = apps.get_model("app", "PlatformConnection")
        Project = apps.get_model("app", "Project")
        Standard = apps.get_model("app", "Standard")
        CommitCheck = apps.get_model("app", "CommitCheck")
        StandardExecution = apps.get_model("app", "StandardExecution")
        tenant = Tenant.objects.create(name="Acme", slug="acme")
        platform = PlatformConnection.objects.create(tenant=tenant, platform="github", display_name="Acme")
        project = Project.objects.create(
            tenant=tenant, platform_connection=platform, platform="github", external_id="1",
            name="api", full_path="acme/api", default_branch="main",
        )
        lint = Standard.objects.create(tenant=tenant, name="Lint")
        docs = Standard.objects.create(tenant=tenant, name="Docs")
        project.standards.add(lint, docs)
        shas = {}
        for sha, statuses in (("a" * 40, ("passed", "failed")), ("b" * 40, ("passed", "error")), ("c" * 40, ("running", "passed"))):
            check = CommitCheck.objects.create(project=project, branch="main", commit_sha=sha, event_type="push")
            for standard, status in zip((lint, docs), statuses):
                StandardExecution.objects.create(
                    project=project, standard=standard, standard_name=standard.name, commit_check=check,
                    status=status, score=100 if status == "passed" else 0,
                )
            shas[sha] = check.pk

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())

        apps = executor.loader.project_state(executor.loader.graph.leaf_nodes()).apps
        scores = {s.commit_sha: s for s in apps.get_model("app", "CommitScore").objects.all()}
        assert (scores["a" * 40].value, scores["a" * 40].failed) == (50, False)
        assert (scores["b" * 40].value, scores["b" * 40].reason) == (None, "Docs errored")
        # Still running: nothing to decide yet.
        assert "c" * 40 not in scores
