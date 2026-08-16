"""Rename the Policy domain to Standard.

Hand-written: the autodetector cannot resolve this many simultaneous model
renames in one pass. Every operation is a rename — no data is created or
dropped, so this is reversible and safe to run against populated databases.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0025_infrastructurecomponent"),
    ]

    operations = [
        # Drop constraints/indexes that name the fields we are about to rename.
        migrations.RemoveConstraint(
            model_name="policyversion",
            name="unique_policy_version",
        ),
        migrations.RemoveIndex(
            model_name="policyexecution",
            name="idx_policyexec_project_date",
        ),
        migrations.RemoveIndex(
            model_name="policyexecution",
            name="idx_policyexec_policy_date",
        ),
        # Models.
        migrations.RenameModel(old_name="PolicyLabel", new_name="StandardLabel"),
        migrations.RenameModel(old_name="Policy", new_name="Standard"),
        migrations.RenameModel(old_name="PolicyVersion", new_name="StandardVersion"),
        migrations.RenameModel(
            old_name="MarketplacePolicy", new_name="MarketplaceStandard"
        ),
        migrations.RenameModel(
            old_name="PolicyExecution", new_name="StandardExecution"
        ),
        # Fields.
        migrations.RenameField(
            model_name="standard",
            old_name="source_marketplace_policy",
            new_name="source_marketplace_standard",
        ),
        migrations.RenameField(
            model_name="standardversion",
            old_name="policy",
            new_name="standard",
        ),
        migrations.RenameField(
            model_name="marketplacepack",
            old_name="policies",
            new_name="standards",
        ),
        migrations.RenameField(
            model_name="standardexecution",
            old_name="policy",
            new_name="standard",
        ),
        migrations.RenameField(
            model_name="standardexecution",
            old_name="policy_name",
            new_name="standard_name",
        ),
        # Tables.
        migrations.AlterModelTable(
            name="standardlabel",
            table="standard_labels",
        ),
        migrations.AlterModelTable(
            name="standard",
            table="standards",
        ),
        migrations.AlterModelTable(
            name="standardversion",
            table="standard_versions",
        ),
        migrations.AlterModelTable(
            name="marketplacestandard",
            table="marketplace_standards",
        ),
        migrations.AlterModelTable(
            name="standardexecution",
            table="standard_executions",
        ),
        # Reverse accessors (state-only, but Django tracks them).
        migrations.AlterField(
            model_name="standardlabel",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="standard_labels",
                to="app.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="standard",
            name="tenant",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="standards",
                to="app.tenant",
            ),
        ),
        migrations.AlterField(
            model_name="standard",
            name="labels",
            field=models.ManyToManyField(
                blank=True,
                related_name="standards",
                to="app.standardlabel",
            ),
        ),
        migrations.AlterField(
            model_name="standard",
            name="source_marketplace_standard",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="installed_standards",
                to="app.marketplacestandard",
            ),
        ),
        migrations.AlterField(
            model_name="standardexecution",
            name="project",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="standard_executions",
                to="app.project",
            ),
        ),
        migrations.AlterField(
            model_name="standardexecution",
            name="triggered_by_user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="standard_executions",
                to="app.user",
            ),
        ),
        # Re-add constraints/indexes under the new names.
        migrations.AddConstraint(
            model_name="standardversion",
            constraint=models.UniqueConstraint(
                fields=("standard", "version"),
                name="unique_standard_version",
            ),
        ),
        migrations.AddIndex(
            model_name="standardexecution",
            index=models.Index(
                fields=["project", "-created_at"],
                name="idx_standardexec_project_date",
            ),
        ),
        migrations.AddIndex(
            model_name="standardexecution",
            index=models.Index(
                fields=["standard", "-created_at"],
                name="idx_standardexec_standard_date",
            ),
        ),
    ]
