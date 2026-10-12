"""The ``platform`` cache's table (Django's database cache).

Created here rather than by ``createcachetable`` so deploys need no extra
step. The schema is the one ``createcachetable`` builds.
"""

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0042_commit_check_committed_at'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS platform_cache (
                    cache_key varchar(255) NOT NULL PRIMARY KEY,
                    value text NOT NULL,
                    expires timestamp with time zone NOT NULL
                );
                CREATE INDEX IF NOT EXISTS platform_cache_expires ON platform_cache (expires);
            """,
            reverse_sql="DROP TABLE IF EXISTS platform_cache;",
        ),
    ]
