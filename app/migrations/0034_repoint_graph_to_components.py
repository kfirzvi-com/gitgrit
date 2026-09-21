"""Components, step 3 of 3: repoint and drop.

The graph tables lose their project FKs and keep only the component FKs
(renamed into place); ``ProjectDependency`` becomes ``ComponentDependency``;
``ProjectStack`` and ``Project.inferred_technologies`` go away.

Reversible: the old project columns are first made nullable, so that on the
way back Django can re-add them empty, ``_refill_project_columns`` populates
them from the component FKs, and only then are they made NOT NULL again.
"""
import django.db.models.deletion
from django.db import migrations, models


def _noop(apps, schema_editor):
    pass


def _refill_project_columns(apps, schema_editor):
    """Reverse helper: derive each edge row's project from its component."""
    ProjectDependency = apps.get_model("app", "ProjectDependency")
    ExternalDependency = apps.get_model("app", "ExternalDependency")
    InfrastructureComponent = apps.get_model("app", "InfrastructureComponent")
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
        ("app", "0033_backfill_root_components"),
    ]

    operations = [
        # Make the outgoing project columns nullable first, so reversing this
        # migration re-adds them nullable, refills them (below), and only then
        # restores NOT NULL.
        migrations.AlterField(
            model_name="projectdependency",
            name="source",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dependencies_out",
                to="app.project",
            ),
        ),
        migrations.AlterField(
            model_name="projectdependency",
            name="target",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dependencies_in",
                to="app.project",
            ),
        ),
        migrations.AlterField(
            model_name="externaldependency",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="external_dependencies",
                to="app.project",
            ),
        ),
        migrations.AlterField(
            model_name="infrastructurecomponent",
            name="project",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="infrastructure_components",
                to="app.project",
            ),
        ),
        migrations.RunPython(_noop, _refill_project_columns),
        # --- ProjectDependency → ComponentDependency -----------------------
        migrations.RemoveConstraint(model_name="projectdependency", name="unique_project_dependency"),
        migrations.RemoveConstraint(model_name="projectdependency", name="project_dependency_no_self_loop"),
        migrations.RemoveField(model_name="projectdependency", name="source"),
        migrations.RemoveField(model_name="projectdependency", name="target"),
        migrations.RenameField(model_name="projectdependency", old_name="source_component", new_name="source"),
        migrations.RenameField(model_name="projectdependency", old_name="target_component", new_name="target"),
        migrations.AlterField(
            model_name="projectdependency",
            name="source",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dependencies_out",
                to="app.component",
            ),
        ),
        migrations.AlterField(
            model_name="projectdependency",
            name="target",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dependencies_in",
                to="app.component",
            ),
        ),
        migrations.RenameModel(old_name="ProjectDependency", new_name="ComponentDependency"),
        migrations.AlterModelTable(name="componentdependency", table="component_dependencies"),
        migrations.AlterField(
            model_name="componentdependency",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="component_dependencies",
                to="app.tenant",
            ),
        ),
        migrations.AddConstraint(
            model_name="componentdependency",
            constraint=models.UniqueConstraint(fields=("source", "target"), name="unique_component_dependency"),
        ),
        migrations.AddConstraint(
            model_name="componentdependency",
            constraint=models.CheckConstraint(
                condition=models.Q(("source", models.F("target")), _negated=True),
                name="component_dependency_no_self_loop",
            ),
        ),
        # --- ExternalDependency --------------------------------------------
        migrations.RemoveConstraint(model_name="externaldependency", name="unique_external_dependency"),
        migrations.RemoveField(model_name="externaldependency", name="project"),
        migrations.AlterField(
            model_name="externaldependency",
            name="component",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="external_dependencies",
                to="app.component",
            ),
        ),
        migrations.AddConstraint(
            model_name="externaldependency",
            constraint=models.UniqueConstraint(
                fields=("component", "name", "direction"), name="unique_external_dependency"
            ),
        ),
        # --- InfrastructureComponent ---------------------------------------
        migrations.RemoveConstraint(model_name="infrastructurecomponent", name="unique_infrastructure_component"),
        migrations.RemoveField(model_name="infrastructurecomponent", name="project"),
        migrations.AlterField(
            model_name="infrastructurecomponent",
            name="component",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="infrastructure_components",
                to="app.component",
            ),
        ),
        migrations.AddConstraint(
            model_name="infrastructurecomponent",
            constraint=models.UniqueConstraint(fields=("component", "name"), name="unique_infrastructure_component"),
        ),
        # --- Project: membership and tech labels now live on components ----
        migrations.RemoveField(model_name="project", name="stacks"),
        migrations.DeleteModel(name="ProjectStack"),
        migrations.RemoveField(model_name="project", name="inferred_technologies"),
    ]
