# LLMRole.last_error / last_error_at: remember why the most recent call through
# a role failed so Workspace Settings → LLM can show it. Before this, a retired
# model (e.g. a provider dropping a model ID) only surfaced as an empty
# architecture map — the error text sat in Project.deps_error, which no page
# rendered.

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0030_disable_draft_standards"),
    ]

    operations = [
        migrations.AddField(
            model_name="llmrole",
            name="last_error",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="llmrole",
            name="last_error_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
