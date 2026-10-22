"""A commit a Required standard failed is a verdict, not a number: its value
is None (it was stored as 0), and a check constraint keeps it that way."""
from django.db import migrations, models


def failed_has_no_value(apps, schema_editor):
    apps.get_model("app", "CommitScore").objects.filter(failed=True).update(value=None)


def failed_reads_zero(apps, schema_editor):
    apps.get_model("app", "CommitScore").objects.filter(failed=True).update(value=0)


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0053_commit_scores"),
    ]

    operations = [
        migrations.RunPython(failed_has_no_value, failed_reads_zero),
        migrations.AddConstraint(
            model_name="commitscore",
            constraint=models.CheckConstraint(
                condition=models.Q(failed=False) | models.Q(value__isnull=True),
                name="commit_score_failed_has_no_value",
            ),
        ),
    ]
