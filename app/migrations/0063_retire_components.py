"""Projects take over from components (phase 1: retire them from the code).

The new release has no ``Component``, ``ComponentStack`` or
``ComponentDependency`` models, and externals/infrastructure belong to a
project. This migration says so to Django's model state only: the tables and
columns stay, because the previous release keeps serving against them until
the new one is live (zero downtime). A later release copies whatever it
wrote in between and drops them (phase 2).

One database change is needed now. Django cascades deletes in Python, and the
new release no longer knows the component tables, so deleting a project,
stack or workspace would trip the component tables' foreign keys to them.
Those constraints are dropped; the previous release still deletes components
first (its Python cascade), so nothing it does changes. Rows the new release
orphans there are discarded with the tables in phase 2.
"""
import django.db.models.deletion
from django.db import migrations, models

COMPONENT_TABLES = ("components", "component_stacks", "component_dependencies")
REFERENCED_TABLES = ("projects", "stacks", "tenants")

DROP_FOREIGN_KEYS_TO_LIVE_TABLES = f"""
DO $$
DECLARE c record;
BEGIN
    FOR c IN
        SELECT conname, conrelid::regclass AS tbl
        FROM pg_constraint
        WHERE contype = 'f'
          AND conrelid::regclass::text IN {COMPONENT_TABLES}
          AND confrelid::regclass::text IN {REFERENCED_TABLES}
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', c.tbl, c.conname);
    END LOOP;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0062_copy_components_onto_projects"),
    ]

    operations = [
        migrations.RunSQL(DROP_FOREIGN_KEYS_TO_LIVE_TABLES, migrations.RunSQL.noop),
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RemoveConstraint(model_name="externaldependency", name="unique_external_dependency"),
                migrations.RemoveConstraint(
                    model_name="infrastructurecomponent", name="unique_infrastructure_component"
                ),
                migrations.RemoveField(model_name="externaldependency", name="component"),
                migrations.RemoveField(model_name="infrastructurecomponent", name="component"),
                migrations.AlterField(
                    model_name="externaldependency",
                    name="project",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="external_dependencies", to="app.project",
                    ),
                ),
                migrations.AlterField(
                    model_name="infrastructurecomponent",
                    name="project",
                    field=models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="infrastructure_components", to="app.project",
                    ),
                ),
                # Enforced in the database by phase 2, after deduping what the
                # previous release wrote meanwhile.
                migrations.AddConstraint(
                    model_name="externaldependency",
                    constraint=models.UniqueConstraint(
                        fields=("project", "name", "direction"), name="unique_project_external_dependency"
                    ),
                ),
                migrations.AddConstraint(
                    model_name="infrastructurecomponent",
                    constraint=models.UniqueConstraint(
                        fields=("project", "name"), name="unique_project_infrastructure"
                    ),
                ),
                migrations.DeleteModel(name="ComponentDependency"),
                migrations.DeleteModel(name="ComponentStack"),
                migrations.DeleteModel(name="Component"),
            ],
            database_operations=[],
        ),
    ]
