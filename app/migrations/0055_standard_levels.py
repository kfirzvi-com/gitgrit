# The boolean Critical mark becomes a level (app.domain.levels): critical=True
# is "critical", everything else "high", on the attachment and on the
# execution snapshot. Reversible: "critical" goes back to True, any other
# level to False.

from django.db import migrations, models

TABLES = ("ProjectStandard", "StandardExecution")


def critical_to_level(apps, schema_editor):
    for name in TABLES:
        model = apps.get_model("app", name)
        model.objects.filter(critical=True).update(level="critical")
        model.objects.filter(critical=False).update(level="high")


def level_to_critical(apps, schema_editor):
    for name in TABLES:
        model = apps.get_model("app", name)
        model.objects.filter(level="critical").update(critical=True)
        model.objects.exclude(level="critical").update(critical=False)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0054_neglect_clock'),
    ]

    operations = [
        migrations.AddField(
            model_name='projectstandard',
            name='level',
            field=models.CharField(choices=[('critical', 'Critical'), ('high', 'High')], default='high', max_length=20),
        ),
        migrations.AddField(
            model_name='standardexecution',
            name='level',
            field=models.CharField(choices=[('critical', 'Critical'), ('high', 'High')], default='high', max_length=20),
        ),
        migrations.RunPython(critical_to_level, level_to_critical),
        migrations.RemoveField(
            model_name='projectstandard',
            name='critical',
        ),
        migrations.RemoveField(
            model_name='standardexecution',
            name='critical',
        ),
        migrations.AddConstraint(
            model_name='projectstandard',
            constraint=models.CheckConstraint(condition=models.Q(('level__in', ['critical', 'high'])), name='project_standard_level_known'),
        ),
        migrations.AddConstraint(
            model_name='standardexecution',
            constraint=models.CheckConstraint(condition=models.Q(('level__in', ['critical', 'high'])), name='standard_execution_level_known'),
        ),
    ]
