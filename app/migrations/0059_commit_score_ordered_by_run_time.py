from django.db import migrations
from django.db.models import OuterRef, Subquery


def order_by_run_time(apps, schema_editor):
    """Existing scores were ordered by their commit's time; order them by
    when their check ran, like new ones."""
    CommitScore = apps.get_model("app", "CommitScore")
    CommitCheck = apps.get_model("app", "CommitCheck")
    CommitScore.objects.update(
        ordered_at=Subquery(CommitCheck.objects.filter(pk=OuterRef("commit_check_id")).values("created_at")[:1])
    )


class Migration(migrations.Migration):
    dependencies = [("app", "0058_user_time_zone")]

    operations = [migrations.RunPython(order_by_run_time, migrations.RunPython.noop)]
