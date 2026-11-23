"""Projects take over from components (step 2 of 2: drop the components).

Removes ``Component``, ``ComponentStack`` and ``ComponentDependency``, and
moves externals and infrastructure onto their project for good (deduped:
two components of one project that named the same service collapse to one
row).

Deploy note: code from before 0061 still reads the component tables, so
between ``migrate`` and the new release going live its stack and map pages
would fail. Ship this migration in the release after 0061, or accept that
short window.

Reversible: going back recreates one root component per project (with its
kind, tech labels and stacks) and points the edges, externals and
infrastructure at it. Suggested projects are not turned back into components.
"""
import django.db.models.deletion
from django.db import migrations, models

def dedupe_onto_projects(apps, schema_editor):
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")
    Component = apps.get_model("app", "Component")
    project_of = dict(Component.objects.values_list("pk", "project_id"))

    for model, key in ((ExternalDependency, ("name", "direction")), (InfrastructureComponent, ("name",))):
        seen = set()
        for row in model.objects.order_by("created_at", "pk"):
            if row.project_id is None:
                row.project_id = project_of.get(row.component_id)
                if row.project_id is None:
                    row.delete()
                    continue
                row.save(update_fields=["project"])
            k = (row.project_id, *(getattr(row, f).lower() if f == "name" else getattr(row, f) for f in key))
            if k in seen:
                row.delete()
            else:
                seen.add(k)


def restore_root_components(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    Component = apps.get_model("app", "Component")
    ComponentStack = apps.get_model("app", "ComponentStack")
    ComponentDependency = apps.get_model("app", "ComponentDependency")
    ProjectStack = apps.get_model("app", "ProjectStack")
    ProjectDependency = apps.get_model("app", "ProjectDependency")
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")

    root = {}
    for project in Project.objects.all():
        root[project.pk] = Component.objects.create(
            tenant_id=project.tenant_id, project=project, path="", name=project.name,
            kind=project.kind, technologies=list(project.technologies or []),
        ).pk
    ComponentStack.objects.bulk_create(
        [ComponentStack(component_id=root[m.project_id], stack_id=m.stack_id) for m in ProjectStack.objects.all()],
        ignore_conflicts=True,
    )
    ComponentDependency.objects.bulk_create(
        [
            ComponentDependency(
                tenant_id=d.tenant_id, source_id=root[d.source_id], target_id=root[d.target_id],
                label=d.label, description=d.description,
            )
            for d in ProjectDependency.objects.all()
        ],
        ignore_conflicts=True,
    )
    for model in (ExternalDependency, InfrastructureComponent):
        for row in model.objects.all():
            row.component_id = root[row.project_id]
            row.save(update_fields=["component"])


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0061_projects_replace_components"),
    ]

    operations = [
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
        migrations.RunPython(dedupe_onto_projects, restore_root_components),
        migrations.RemoveConstraint(model_name="externaldependency", name="unique_external_dependency"),
        migrations.RemoveConstraint(model_name="infrastructurecomponent", name="unique_infrastructure_component"),
        migrations.RemoveField(model_name="externaldependency", name="component"),
        migrations.RemoveField(model_name="infrastructurecomponent", name="component"),
        migrations.AlterField(
            model_name="externaldependency",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="external_dependencies", to="app.project"
            ),
        ),
        migrations.AlterField(
            model_name="infrastructurecomponent",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="infrastructure_components", to="app.project"
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldependency",
            constraint=models.UniqueConstraint(
                fields=("project", "name", "direction"), name="unique_project_external_dependency"
            ),
        ),
        migrations.AddConstraint(
            model_name="infrastructurecomponent",
            constraint=models.UniqueConstraint(fields=("project", "name"), name="unique_project_infrastructure"),
        ),
        migrations.DeleteModel(name="ComponentDependency"),
        migrations.DeleteModel(name="ComponentStack"),
        migrations.DeleteModel(name="Component"),
    ]
