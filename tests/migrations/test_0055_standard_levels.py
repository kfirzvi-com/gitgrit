"""Migration 0055 turns the boolean Critical mark into a level, on the
attachment and on the execution snapshot: True is "critical", False is
"high"; reversing maps "critical" back to True and any other level to False."""
import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

BEFORE = [("app", "0054_neglect_clock")]
AFTER = [("app", "0055_standard_levels")]


def _migrate(target):
    executor = MigrationExecutor(connection)
    executor.loader.build_graph()
    executor.migrate(target)
    return executor.loader.project_state(target).apps


def _latest():
    return MigrationExecutor(connection).loader.graph.leaf_nodes()


@pytest.mark.django_db(transaction=True)
class StandardLevelsMigrationTests(TransactionTestCase):
    def tearDown(self):
        _migrate(_latest())
        super().tearDown()

    def _rows(self, apps, critical_flags):
        Tenant = apps.get_model("app", "Tenant")
        Project = apps.get_model("app", "Project")
        Standard = apps.get_model("app", "Standard")
        ProjectStandard = apps.get_model("app", "ProjectStandard")
        StandardExecution = apps.get_model("app", "StandardExecution")
        tenant = Tenant.objects.create(name="t", slug="t")
        connection_ = apps.get_model("app", "PlatformConnection").objects.create(
            tenant=tenant, platform="github"
        )
        project = Project.objects.create(
            tenant=tenant, platform_connection=connection_, name="p", external_id="1"
        )
        ids = []
        for i, critical in enumerate(critical_flags):
            standard = Standard.objects.create(tenant=tenant, name=f"s{i}")
            ProjectStandard.objects.create(project=project, standard=standard, critical=critical)
            StandardExecution.objects.create(
                project=project, standard=standard, standard_name=standard.name,
                event_type="manual", status="failed", critical=critical,
            )
            ids.append(standard.pk)
        return ids

    def test_forward_maps_true_to_critical_and_false_to_high_then_back(self):
        old = _migrate(BEFORE)
        gate, plain = self._rows(old, [True, False])

        new = _migrate(AFTER)
        for model in ("ProjectStandard", "StandardExecution"):
            rows = dict(new.get_model("app", model).objects.values_list("standard_id", "level"))
            assert rows == {gate: "critical", plain: "high"}, model

        back = _migrate(BEFORE)
        for model in ("ProjectStandard", "StandardExecution"):
            rows = dict(back.get_model("app", model).objects.values_list("standard_id", "critical"))
            assert rows == {gate: True, plain: False}, model
