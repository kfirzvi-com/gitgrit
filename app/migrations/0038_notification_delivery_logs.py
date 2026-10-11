"""Split NotificationDelivery into InboxItem and DeliveryLog (step 1 of 2: data).

NotificationDelivery mixed two things: a person's inbox copy (recipient,
read_at) and the outcome of delivering on a channel (channel, status, error).
Each channel's outcome becomes one DeliveryLog row; the sent inbox rows are
kept (0039 renames them to InboxItem); everything else is dropped.
"""

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def split_deliveries(apps, schema_editor):
    NotificationDelivery = apps.get_model("app", "NotificationDelivery")
    DeliveryLog = apps.get_model("app", "DeliveryLog")

    outcomes = {}
    for row in NotificationDelivery.objects.order_by("created_at"):
        key = (row.notification_id, row.channel)
        sent, error = outcomes.get(key, (False, ""))
        outcomes[key] = (sent or row.status == "sent", error or row.error)
    DeliveryLog.objects.bulk_create(
        DeliveryLog(
            notification_id=notification_id,
            channel=channel,
            status="sent" if sent else "failed",
            error="" if sent else error,
        )
        for (notification_id, channel), (sent, error) in outcomes.items()
    )

    NotificationDelivery.objects.exclude(
        channel="inbox", status="sent", recipient__isnull=False
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0037_remove_notificationdelivery_pinned_at"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="DeliveryLog",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("channel", models.CharField(max_length=50)),
                ("status", models.CharField(choices=[("sent", "Sent"), ("failed", "Failed")], max_length=10)),
                ("error", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("notification", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="delivery_logs", to="app.notification")),
            ],
            options={
                "db_table": "notification_delivery_logs",
                "ordering": ["-created_at"],
            },
        ),
        migrations.RunPython(split_deliveries, migrations.RunPython.noop),
    ]
