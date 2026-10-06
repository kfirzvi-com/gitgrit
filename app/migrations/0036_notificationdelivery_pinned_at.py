from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0035_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="notificationdelivery",
            name="pinned_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
