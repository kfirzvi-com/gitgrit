"""Seed a minimal tenant + project + policy + APIToken for plugin integration tests.

Idempotent on the tenant/user/connection/project/policy; always mints a fresh
APIToken per invocation (tokens aren't readable after creation, so the script
has to print one at some point).

Output is one `KEY=value` pair per line on stdout so the shell harness can
`eval $(python manage.py seed_plugin_scenario)`:

    MCP_TOKEN=grit_...
    TENANT_ID=<uuid>
    PROJECT_ID=<uuid>
    FULL_PATH=acme/backend
    WEB_URL=https://github.com/acme/backend
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from app.domain.models import (
    APIToken,
    Membership,
    PlatformConnection,
    Policy,
    Project,
    Tenant,
    User,
)

# Policy that forbids "TODO" markers — used by Layer 4's violating-edit scenario.
_POLICY_CODE = '''def evaluate(project):
    """Fail if any tracked source file contains a TODO marker."""
    offenders = []
    for path in project.list_files():
        if not path.endswith((".py", ".js", ".ts")):
            continue
        content = project.get_file_content(path) or ""
        if "TODO" in content:
            offenders.append(path)
    if offenders:
        return {
            "passed": False,
            "score": 0,
            "message": f"Found TODO markers in {len(offenders)} file(s)",
            "details": {"offenders": offenders},
        }
    return {
        "passed": True,
        "score": 100,
        "message": "No TODO markers found",
        "details": {},
    }
'''


class Command(BaseCommand):
    help = "Seed a minimal GitGrit scenario (tenant/project/policy/token) for plugin tests."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-slug", default="plugin-test")
        parser.add_argument("--username", default="plugin-test-user")
        parser.add_argument("--full-path", default="acme/backend")
        parser.add_argument("--web-url", default="https://github.com/acme/backend")
        parser.add_argument("--project-name", default="acme/backend")
        parser.add_argument("--token-name", default="plugin-scenario")
        parser.add_argument(
            "--no-policies",
            action="store_true",
            help=(
                "Skip creating the No-TODOs policy and disable any existing policies "
                "for the tenant. Used by the empty-policies plugin scenario."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **opts):
        tenant, _ = Tenant.objects.get_or_create(
            slug=opts["tenant_slug"],
            defaults={"name": "Plugin Test Tenant"},
        )
        user, _ = User.objects.get_or_create(
            username=opts["username"],
            defaults={"email": f"{opts['username']}@example.com"},
        )
        Membership.objects.get_or_create(
            user=user,
            tenant=tenant,
            defaults={"role": Membership.Role.OWNER},
        )
        connection, _ = PlatformConnection.objects.get_or_create(
            tenant=tenant,
            platform="github",
            defaults={
                "display_name": "plugin-test-github",
                "base_url": "https://api.github.com",
                "access_token": "plugin-test-fake-access-token",
            },
        )
        project, _ = Project.objects.update_or_create(
            tenant=tenant,
            platform_connection=connection,
            external_id=f"plugin-test:{opts['full_path']}",
            defaults={
                "platform": "github",
                "name": opts["project_name"],
                "full_path": opts["full_path"],
                "web_url": opts["web_url"],
                "default_branch": "main",
                "languages": ["Python", "JavaScript"],
            },
        )
        if opts["no_policies"]:
            # Empty-policies scenario: ensure no enabled, non-draft policies remain
            # for this tenant so `list_active_for_project` returns []. Disabling
            # (rather than deleting) keeps re-runs idempotent — a subsequent
            # default seed will re-enable via update_or_create on the same name.
            Policy.objects.filter(tenant=tenant).update(enabled=False)
        else:
            Policy.objects.update_or_create(
                tenant=tenant,
                name="No TODOs in source",
                defaults={
                    "description": "Fails if any tracked Python/JS/TS file contains a TODO marker.",
                    "code": _POLICY_CODE,
                    "criteria": {
                        "events": ["push", "pull_request"],
                        "ref": "",
                        "languages": ["Python"],
                    },
                    "enabled": True,
                    "draft": False,
                },
            )
        token, raw = APIToken.generate()
        token.user = user
        token.tenant = tenant
        token.name = opts["token_name"]
        token.save()

        self.stdout.write(f"MCP_TOKEN={raw}")
        self.stdout.write(f"TENANT_ID={tenant.id}")
        self.stdout.write(f"PROJECT_ID={project.id}")
        self.stdout.write(f"TOKEN_PREFIX={token.prefix}")
        self.stdout.write(f"FULL_PATH={opts['full_path']}")
        self.stdout.write(f"WEB_URL={opts['web_url']}")
