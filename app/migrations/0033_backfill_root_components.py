"""Components, step 2 of 3: data.

Every existing project gets one root component (``path=""``) carrying the
project's name and inferred technologies. Stack memberships and the three
graph tables are pointed at that root component. Reversible: the reverse
copies component data back onto the project columns 0034 would otherwise
have dropped.
"""
from django.db import migrations


def forwards(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    Component = apps.get_model("app", "Component")
    ComponentStack = apps.get_model("app", "ComponentStack")
    ProjectStack = apps.get_model("app", "ProjectStack")
    ProjectDependency = apps.get_model("app", "ProjectDependency")
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")

    for project in Project.objects.all().iterator():
        root, _ = Component.objects.get_or_create(
            project=project,
            path="",
            defaults={
                "tenant_id": project.tenant_id,
                "name": project.name,
                "technologies": project.inferred_technologies or [],
            },
        )
        ComponentStack.objects.bulk_create(
            [
                ComponentStack(component=root, stack_id=stack_id)
                for stack_id in ProjectStack.objects.filter(project=project).values_list(
                    "stack_id", flat=True
                )
            ],
            ignore_conflicts=True,
        )
        ProjectDependency.objects.filter(source=project).update(source_component=root)
        ProjectDependency.objects.filter(target=project).update(target_component=root)
        ExternalDependency.objects.filter(project=project).update(component=root)
        InfrastructureComponent.objects.filter(project=project).update(component=root)

    # Zero-loss checks before 0034 drops the old columns.
    assert Component.objects.count() >= Project.objects.count()
    assert not ProjectDependency.objects.filter(source_component__isnull=True).exists()
    assert not ProjectDependency.objects.filter(target_component__isnull=True).exists()
    assert not ExternalDependency.objects.filter(component__isnull=True).exists()
    assert not InfrastructureComponent.objects.filter(component__isnull=True).exists()


def backwards(apps, schema_editor):
    Project = apps.get_model("app", "Project")
    Component = apps.get_model("app", "Component")
    ProjectStack = apps.get_model("app", "ProjectStack")
    ProjectDependency = apps.get_model("app", "ProjectDependency")
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")

    for root in Component.objects.filter(path="").select_related("project").iterator():
        Project.objects.filter(pk=root.project_id).update(
            inferred_technologies=root.technologies or []
        )
        ProjectStack.objects.bulk_create(
            [
                ProjectStack(project_id=root.project_id, stack_id=stack_id)
                for stack_id in root.component_stacks.values_list("stack_id", flat=True)
            ],
            ignore_conflicts=True,
        )
    for dep in ProjectDependency.objects.select_related("source_component", "target_component"):
        ProjectDependency.objects.filter(pk=dep.pk).update(
            source_id=dep.source_component.project_id,
            target_id=dep.target_component.project_id,
        )
    for ext in ExternalDependency.objects.select_related("component"):
        ExternalDependency.objects.filter(pk=ext.pk).update(project_id=ext.component.project_id)
    for ic in InfrastructureComponent.objects.select_related("component"):
        InfrastructureComponent.objects.filter(pk=ic.pk).update(project_id=ic.component.project_id)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0032_component_and_componentstack"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
