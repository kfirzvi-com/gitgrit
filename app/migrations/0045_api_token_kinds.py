"""Split API tokens into personal and workspace tokens.

Existing tokens were minted for the retired MCP server: each was tied to a
user *and* a workspace, which matches neither new kind. Rather than silently
widening them (personal: every workspace the user is in) or detaching them
from their user (workspace), they are deleted; people create new ones.
"""
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def delete_mcp_tokens(apps, schema_editor):
    apps.get_model("app", "APIToken").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0044_register_gitgrit_cli_oauth_client"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.RunPython(delete_mcp_tokens, migrations.RunPython.noop),
        migrations.RemoveField(model_name="apitoken", name="client_kind"),
        migrations.AddField(
            model_name="apitoken",
            name="kind",
            field=models.CharField(
                choices=[("personal", "Personal"), ("workspace", "Workspace")],
                default="personal",
                max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AlterField(
            model_name="apitoken",
            name="user",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="api_tokens",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AlterField(
            model_name="apitoken",
            name="tenant",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="api_tokens",
                to="app.tenant",
            ),
        ),
        migrations.AddField(
            model_name="apitoken",
            name="created_by",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="+",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddConstraint(
            model_name="apitoken",
            constraint=models.CheckConstraint(
                condition=(
                    models.Q(kind="personal", user__isnull=False, tenant__isnull=True)
                    | models.Q(kind="workspace", user__isnull=True, tenant__isnull=False)
                ),
                name="api_token_owner_matches_kind",
            ),
        ),
    ]
