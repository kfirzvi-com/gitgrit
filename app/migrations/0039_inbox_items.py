"""Split NotificationDelivery into InboxItem and DeliveryLog (step 2 of 2:
schema). Kept apart from 0038's data move so Postgres never alters a table
with pending trigger events in the same transaction."""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0038_notification_delivery_logs"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RemoveIndex(model_name="notificationdelivery", name="idx_notifdelivery_bell"),
        migrations.RemoveField(model_name="notificationdelivery", name="channel"),
        migrations.RemoveField(model_name="notificationdelivery", name="status"),
        migrations.RemoveField(model_name="notificationdelivery", name="error"),
        migrations.RemoveField(model_name="notificationdelivery", name="sent_at"),
        migrations.RenameModel(old_name="NotificationDelivery", new_name="InboxItem"),
        migrations.AlterModelTable(name="inboxitem", table="inbox_items"),
        migrations.AlterField(
            model_name="inboxitem",
            name="notification",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inbox_items", to="app.notification"),
        ),
        migrations.AlterField(
            model_name="inboxitem",
            name="recipient",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="inbox_items", to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddIndex(
            model_name="inboxitem",
            index=models.Index(fields=["recipient", "read_at"], name="idx_inbox_item_unread"),
        ),
        migrations.RemoveField(model_name="notification", name="dedupe_key"),
    ]
