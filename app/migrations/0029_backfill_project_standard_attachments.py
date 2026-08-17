# Data migration: backfill standard attachments for existing projects.
#
# Before attachments existed, every enabled non-draft standard in a workspace
# implicitly ran on every project in that workspace. Attaching every existing
# standard to every existing project of the same tenant preserves that
# behavior exactly; only projects/standards created after this migration
# start from "nothing attached by default".

from django.db import migrations


def attach_all_tenant_standards(apps, schema_editor):
    """Attach every standard to every project within each tenant.

    All standards are attached — including disabled ones and drafts — so a
    standard later re-enabled or published keeps running workspace-wide,
    exactly as it would have before attachments existed.
    """
    Project = apps.get_model("app", "Project")
    Standard = apps.get_model("app", "Standard")
    ProjectStandard = apps.get_model("app", "ProjectStandard")

    # order_by() clears Project.Meta.ordering, which would otherwise leak the
    # ordering column into SELECT DISTINCT and yield duplicate tenant ids.
    tenant_ids = (
        Project.objects.order_by()
        .values_list("tenant_id", flat=True)
        .distinct()
    )
    for tenant_id in tenant_ids:
        project_ids = Project.objects.filter(tenant_id=tenant_id).values_list(
            "id", flat=True
        )
        standard_ids = Standard.objects.filter(tenant_id=tenant_id).values_list(
            "id", flat=True
        )
        ProjectStandard.objects.bulk_create(
            [
                ProjectStandard(project_id=project_id, standard_id=standard_id)
                for project_id in project_ids
                for standard_id in standard_ids
            ],
            batch_size=1000,
            ignore_conflicts=True,
        )


def detach_all(apps, schema_editor):
    # Reverse restores the pre-attachment world: no rows in the join table.
    ProjectStandard = apps.get_model("app", "ProjectStandard")
    ProjectStandard.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0028_projectstandard_project_standards_and_more"),
    ]

    operations = [
        migrations.RunPython(attach_all_tenant_standards, detach_all),
    ]
