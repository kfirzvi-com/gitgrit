"""Register the GitGrit CLI as a public OAuth 2.0 client.

A native app: no client secret, authorization code + PKCE, and a loopback
redirect. django-oauth-toolkit accepts any port on a registered 127.0.0.1 /
[::1] redirect (RFC 8252 §7.3), so the CLI may listen on an ephemeral port.
"""
from django.db import migrations
from oauth2_provider.settings import APPLICATION_MODEL

CLIENT_ID = "gitgrit-cli"


def register(apps, schema_editor):
    app_label, model_name = APPLICATION_MODEL.split(".")
    Application = apps.get_model(app_label, model_name)
    Application.objects.update_or_create(
        client_id=CLIENT_ID,
        defaults={
            "name": "GitGrit CLI",
            "client_type": "public",
            "authorization_grant_type": "authorization-code",
            "redirect_uris": "http://127.0.0.1/callback http://[::1]/callback",
            "client_secret": "",
            "skip_authorization": False,
        },
    )


def unregister(apps, schema_editor):
    app_label, model_name = APPLICATION_MODEL.split(".")
    apps.get_model(app_label, model_name).objects.filter(client_id=CLIENT_ID).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("app", "0043_platform_cache"),
        ("oauth2_provider", "0022_refreshtoken_token_family_index"),
    ]

    operations = [migrations.RunPython(register, unregister)]
