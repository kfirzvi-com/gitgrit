# Data migration: enforce "a draft standard is always disabled" on existing rows.
#
# Drafts never run (every runnable predicate checks `enabled and not draft`),
# so an enabled draft was always functionally inert — but it showed a green
# "Enabled" badge next to "Draft" in the standard list, contradicting the
# invariant the forms, toggle, and service layer now enforce.

from django.db import migrations


def disable_draft_standards(apps, schema_editor):
    Standard = apps.get_model("app", "Standard")
    Standard.objects.filter(draft=True, enabled=True).update(enabled=False)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0029_backfill_project_standard_attachments"),
    ]

    operations = [
        # No reverse: enabled+draft was meaningless, nothing to restore.
        migrations.RunPython(disable_draft_standards, migrations.RunPython.noop),
    ]
