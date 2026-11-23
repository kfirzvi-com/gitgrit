"""Projects take over from components (phase 1a: add the project-level schema).

A monorepo's apps and services become projects of their own (rooted at a
path), so the architecture graph, stacks and dependency edges hang off
projects. This migration only *adds* the project-level tables and columns;
0062 copies the component data into them (a separate migration: Django
creates foreign-key indexes at the end of a migration, which Postgres refuses
after rows were written in the same transaction).

Zero downtime: ``migrate`` runs before the new release goes live, so the
previous release keeps serving against this schema for a while. Nothing it
reads or writes goes away: the component tables stay, the new project
columns get database defaults (it inserts projects without them),
externals/infrastructure may now have no component (the new release writes
them by project only), and (0062) the new tables cascade deletes in the
database (its Python cascade doesn't know them). 0063 retires the components from the new code's view
only; a later release drops their tables after copying again whatever the
previous release wrote in between (``copy_components`` is idempotent).

The copy, per project:
* stack memberships of any of its components -> the project's;
* the root component's kind and technologies -> the project's;
* every non-root component -> a *suggested project* (with the stacks it was
  in, so adding it restores its memberships);
* component edges -> project edges (both ends mapped to their projects;
  edges inside one repository collapse away until its projects are added);
* externals and infrastructure -> their component's project.
"""

import uuid

import django.db.models.deletion
from django.db import migrations, models

KINDS = [
    ("service", "Service / API"),
    ("frontend", "Frontend / app"),
    ("library", "Shared library"),
    ("job", "Job / pipeline"),
    ("infra", "Infrastructure as code"),
    ("other", "Other"),
]


# ``component_dependencies`` was once ``project_dependencies`` (0020, renamed
# in 0034) and kept that name's indexes; free the names for the new table.
_LEGACY_INDEXES = (
    "pkey",
    "source_component_id_2cef7e1e",
    "target_component_id_3ec56867",
    "tenant_id_18ff81f5",
)
RENAME_LEGACY_INDEXES = ";".join(
    f'ALTER INDEX IF EXISTS "project_dependencies_{s}" RENAME TO "component_dependencies_{s}"'
    for s in _LEGACY_INDEXES
)
RESTORE_LEGACY_INDEXES = ";".join(
    f'ALTER INDEX IF EXISTS "component_dependencies_{s}" RENAME TO "project_dependencies_{s}"'
    for s in _LEGACY_INDEXES
)


# The previous release inserts projects without these columns.
OLD_RELEASE_DEFAULTS = """
    ALTER TABLE projects ALTER COLUMN kind SET DEFAULT 'other';
    ALTER TABLE projects ALTER COLUMN technologies SET DEFAULT '[]'::jsonb;
    ALTER TABLE projects ALTER COLUMN suggested_projects SET DEFAULT '[]'::jsonb;
"""
DROP_OLD_RELEASE_DEFAULTS = """
    ALTER TABLE projects ALTER COLUMN kind DROP DEFAULT;
    ALTER TABLE projects ALTER COLUMN technologies DROP DEFAULT;
    ALTER TABLE projects ALTER COLUMN suggested_projects DROP DEFAULT;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0060_project_root_path"),
    ]

    operations = [
        migrations.AddField(
            model_name="project",
            name="kind",
            field=models.CharField(choices=KINDS, default="other", max_length=10),
        ),
        migrations.AddField(
            model_name="project",
            name="technologies",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="project",
            name="suggested_projects",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name="ProjectStack",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="project_stacks", to="app.project"
                    ),
                ),
                (
                    "stack",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="project_stacks", to="app.stack"
                    ),
                ),
            ],
            options={"db_table": "project_stacks"},
        ),
        migrations.AddConstraint(
            model_name="projectstack",
            constraint=models.UniqueConstraint(fields=("project", "stack"), name="unique_project_stack"),
        ),
        migrations.AddField(
            model_name="project",
            name="stacks",
            field=models.ManyToManyField(
                blank=True, related_name="projects", through="app.ProjectStack", to="app.stack"
            ),
        ),
        migrations.RunSQL(RENAME_LEGACY_INDEXES, RESTORE_LEGACY_INDEXES),
        migrations.CreateModel(
            name="ProjectDependency",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("label", models.CharField(blank=True, default="", max_length=255)),
                ("description", models.TextField(blank=True, default="")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "source",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="dependencies_out", to="app.project"
                    ),
                ),
                (
                    "target",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="dependencies_in", to="app.project"
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="project_dependencies", to="app.tenant"
                    ),
                ),
            ],
            options={"db_table": "project_dependencies"},
        ),
        migrations.AddConstraint(
            model_name="projectdependency",
            constraint=models.UniqueConstraint(fields=("source", "target"), name="unique_project_dependency"),
        ),
        migrations.AddConstraint(
            model_name="projectdependency",
            constraint=models.CheckConstraint(
                condition=models.Q(("source", models.F("target")), _negated=True),
                name="project_dependency_no_self_loop",
            ),
        ),
        migrations.AddField(
            model_name="externaldependency",
            name="project",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="external_dependencies", to="app.project",
            ),
        ),
        migrations.AddField(
            model_name="infrastructurecomponent",
            name="project",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="infrastructure_components", to="app.project",
            ),
        ),
        migrations.AlterField(
            model_name="externaldependency",
            name="component",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="external_dependencies", to="app.component",
            ),
        ),
        migrations.AlterField(
            model_name="infrastructurecomponent",
            name="component",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE,
                related_name="infrastructure_components", to="app.component",
            ),
        ),
        migrations.RunSQL(OLD_RELEASE_DEFAULTS, DROP_OLD_RELEASE_DEFAULTS),
    ]
