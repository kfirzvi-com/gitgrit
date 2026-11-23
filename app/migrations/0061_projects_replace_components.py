"""Projects take over from components (step 1 of 2: add and copy).

A monorepo's apps and services become projects of their own (rooted at a
path), so the architecture graph, stacks and dependency edges hang off
projects. This migration only *adds* the project-level tables and columns
and copies the component data into them; the component tables stay, so code
from the previous release keeps working against this schema.
0062 drops them.

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


def copy_components(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    Component = apps.get_model("app", "Component")
    ComponentStack = apps.get_model("app", "ComponentStack")
    ComponentDependency = apps.get_model("app", "ComponentDependency")
    ProjectStack = apps.get_model("app", "ProjectStack")
    ProjectDependency = apps.get_model("app", "ProjectDependency")
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")

    stacks_of: dict = {}
    for component_id, stack_id in ComponentStack.objects.values_list("component_id", "stack_id"):
        stacks_of.setdefault(component_id, []).append(str(stack_id))

    memberships = set()
    for project in Project.objects.all():
        components = list(Component.objects.filter(project=project).order_by("path"))
        suggestions = []
        for c in components:
            for stack_id in stacks_of.get(c.pk, ()):
                memberships.add((project.pk, stack_id))
            if c.path == "":
                project.kind = c.kind
                project.technologies = list(c.technologies or [])
            else:
                suggestions.append(
                    {
                        "path": c.path,
                        "name": c.name,
                        "kind": c.kind,
                        "description": c.description,
                        "technologies": list(c.technologies or []),
                        "stack_ids": stacks_of.get(c.pk, []),
                    }
                )
        project.suggested_projects = suggestions
        project.save(update_fields=["kind", "technologies", "suggested_projects"])
    ProjectStack.objects.bulk_create(
        [ProjectStack(project_id=p, stack_id=s) for p, s in memberships], ignore_conflicts=True
    )

    project_of = dict(Component.objects.values_list("pk", "project_id"))
    edges = {}
    for d in ComponentDependency.objects.all():
        source, target = project_of.get(d.source_id), project_of.get(d.target_id)
        if source and target and source != target and (source, target) not in edges:
            edges[(source, target)] = ProjectDependency(
                tenant_id=d.tenant_id, source_id=source, target_id=target,
                label=d.label, description=d.description,
            )
    ProjectDependency.objects.bulk_create(edges.values(), ignore_conflicts=True)

    for model in (ExternalDependency, InfrastructureComponent):
        for row in model.objects.filter(project__isnull=True).only("pk", "component_id"):
            row.project_id = project_of.get(row.component_id)
            row.save(update_fields=["project"])


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
        migrations.RunPython(copy_components, migrations.RunPython.noop),
    ]
