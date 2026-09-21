"""Components, step 1 of 3: additive schema.

Adds the ``Component`` / ``ComponentStack`` tables and *nullable* component
FKs next to the existing project FKs on the three graph tables, so 0033 can
copy data across while both sets of columns exist. 0034 drops the old ones.
"""
import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0031_project_deps_evidence"),
    ]

    operations = [
        migrations.CreateModel(
            name="Component",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("path", models.CharField(blank=True, default="", max_length=1024)),
                ("name", models.CharField(max_length=255)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("service", "Service / API"),
                            ("frontend", "Frontend / app"),
                            ("library", "Shared library"),
                            ("job", "Job / pipeline"),
                            ("infra", "Infrastructure as code"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=10,
                    ),
                ),
                ("description", models.TextField(blank=True, default="")),
                ("technologies", models.JSONField(blank=True, default=list)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="components",
                        to="app.project",
                    ),
                ),
                (
                    "tenant",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="components",
                        to="app.tenant",
                    ),
                ),
            ],
            options={
                "db_table": "components",
                "ordering": ["project__name", "path"],
            },
        ),
        migrations.CreateModel(
            name="ComponentStack",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "component",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="component_stacks",
                        to="app.component",
                    ),
                ),
                (
                    "stack",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="component_stacks",
                        to="app.stack",
                    ),
                ),
            ],
            options={"db_table": "component_stacks"},
        ),
        migrations.AddField(
            model_name="component",
            name="stacks",
            field=models.ManyToManyField(
                blank=True,
                related_name="components",
                through="app.ComponentStack",
                to="app.stack",
            ),
        ),
        migrations.AddConstraint(
            model_name="component",
            constraint=models.UniqueConstraint(fields=("project", "path"), name="unique_component_path"),
        ),
        migrations.AddConstraint(
            model_name="componentstack",
            constraint=models.UniqueConstraint(fields=("component", "stack"), name="unique_component_stack"),
        ),
        # Temporary nullable component FKs alongside the project FKs.
        migrations.AddField(
            model_name="projectdependency",
            name="source_component",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dependencies_out",
                to="app.component",
            ),
        ),
        migrations.AddField(
            model_name="projectdependency",
            name="target_component",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="dependencies_in",
                to="app.component",
            ),
        ),
        migrations.AddField(
            model_name="externaldependency",
            name="component",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="external_dependencies",
                to="app.component",
            ),
        ),
        migrations.AddField(
            model_name="infrastructurecomponent",
            name="component",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="infrastructure_components",
                to="app.component",
            ),
        ),
    ]
