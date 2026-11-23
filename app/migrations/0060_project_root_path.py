"""A project can sit at a root path inside its repository.

Zero downtime: the previous release keeps running against this schema until
the new one is live, and it inserts projects without ``root_path``. The
column therefore gets a database default ("" = the whole repository) on top
of Django's Python-side one.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0059_commit_score_ordered_by_run_time'),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name='project',
            name='unique_tenant_connection_project',
        ),
        migrations.AddField(
            model_name='project',
            name='root_path',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
        migrations.RunSQL(
            "ALTER TABLE projects ALTER COLUMN root_path SET DEFAULT ''",
            "ALTER TABLE projects ALTER COLUMN root_path DROP DEFAULT",
        ),
        migrations.AddConstraint(
            model_name='project',
            constraint=models.UniqueConstraint(fields=('tenant', 'platform_connection', 'external_id', 'root_path'), name='unique_tenant_connection_project_path'),
        ),
    ]
