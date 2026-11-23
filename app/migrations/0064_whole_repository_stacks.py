"""Repair: a whole-repository project keeps only its root component's stacks.

The first version of 0062 put a project into every stack any of its
components was in, so a monorepo's whole-repository project landed in each
of its services' stacks. Those stacks belong to the services, waiting on
their suggestions until they are added as projects (0062 now copies only the
root component's). This removes the memberships that copy made and the root
component didn't have; memberships added since (created after 0062 ran) stay.
A database migrated by the corrected 0062 has nothing to remove.

Zero downtime: the previous release never reads project_stacks.
"""
from django.db import migrations

REMOVE_COPIED_STACKS = """
DELETE FROM project_stacks ps
USING django_migrations m
WHERE m.app = 'app' AND m.name = '0062_copy_components_onto_projects'
  AND ps.created_at <= m.applied
  AND EXISTS (SELECT 1 FROM components c WHERE c.project_id = ps.project_id)
  AND NOT EXISTS (
      SELECT 1 FROM components c
      JOIN component_stacks cs ON cs.component_id = c.id
      WHERE c.project_id = ps.project_id AND c.path = '' AND cs.stack_id = ps.stack_id
  );
"""


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0063_retire_components"),
    ]

    operations = [
        migrations.RunSQL(REMOVE_COPIED_STACKS, migrations.RunSQL.noop),
    ]
