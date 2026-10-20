"""Bringing repositories into a workspace and managing them there.

Connections, the repositories reachable through them, adding a project
(metadata, webhook, first run), editing and removing one, and which standards
are attached to it. The web views and the public API both go through here, so
a project added from the CLI is set up exactly like one added in the browser.

``user`` is whoever acts — None for a workspace token, which has no person.
"""
import logging
import secrets
import uuid
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import ValidationError

from app.application import stack_service
from app.application.errors import NotFoundError
from app.application.event_bus import publish
from app.domain.events import ProjectCreated, ProjectDeleted, StandardsAttached
from app.domain.models import (
    AuthMethod,
    Platform,
    PlatformConnection,
    Project,
    ProjectStandard,
    Stack,
    Standard,
    Tenant,
    User,
)
from app.infrastructure.platform_client import get_platform_client

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 25


class PlatformError(Exception):
    """The git platform couldn't be reached or refused the request."""


class AlreadyAdded(ValueError):
    """The repository is already a project in this workspace."""

    def __init__(self, project: Project):
        super().__init__(f'"{project.full_path or project.name}" is already a project in this workspace.')
        self.project = project


@dataclass(frozen=True)
class AddedProject:
    project: Project
    webhook_ok: bool  # False when a per-repo webhook was needed and couldn't be registered
    runs: dict | None  # the first run's enqueue summary, None when nothing was queued


# --- connections -------------------------------------------------------------


def list_connections(tenant: Tenant) -> list[PlatformConnection]:
    return list(PlatformConnection.objects.filter(tenant=tenant).order_by("created_at"))


def get_connection(tenant: Tenant, connection_id) -> PlatformConnection:
    try:
        return PlatformConnection.objects.get(id=connection_id, tenant=tenant)
    except (PlatformConnection.DoesNotExist, ValidationError, ValueError):
        raise NotFoundError("Connection not found.")


def add_token_connection(
    tenant: Tenant, platform: str, access_token: str, *, display_name: str = "", base_url: str = ""
) -> PlatformConnection:
    """Connect a platform with a personal access token. Unnamed connections
    are called after the platform ("GitHub", then "GitHub 2", …)."""
    access_token = access_token.strip()
    if not access_token:
        raise ValueError("Access token is required.")
    if platform not in (Platform.GITHUB, Platform.GITLAB):
        raise ValueError("Invalid platform.")
    display_name = display_name.strip()
    if not display_name:
        base_name = {Platform.GITHUB: "GitHub", Platform.GITLAB: "GitLab"}[platform]
        taken = set(
            PlatformConnection.objects.filter(tenant=tenant).values_list("display_name", flat=True)
        )
        display_name, n = base_name, 2
        while display_name in taken:
            display_name, n = f"{base_name} {n}", n + 1
    return PlatformConnection.objects.create(
        tenant=tenant,
        platform=platform,
        display_name=display_name,
        base_url=base_url.strip(),
        access_token=access_token,
    )


# --- repositories ------------------------------------------------------------


def search_repositories(
    tenant: Tenant, connection: PlatformConnection, query: str = "", limit: int = SEARCH_LIMIT
) -> list[dict]:
    """Repositories reachable through ``connection`` whose path matches
    ``query``, each marked ``already_added`` when it's a project here."""
    try:
        results = get_platform_client(connection).search_projects(query.strip())
    except Exception as exc:
        logger.exception("Failed to search repositories on connection %s", connection.pk)
        raise PlatformError("Couldn't search the git platform. Check the connection.") from exc
    added = set(
        Project.objects.filter(tenant=tenant, platform_connection=connection).values_list(
            "external_id", flat=True
        )
    )
    for r in results:
        r["already_added"] = r["external_id"] in added
    return results[:limit]


def find_repository(tenant: Tenant, connection: PlatformConnection, ref: str) -> dict:
    """The repository ``ref`` names — its path (``org/repo``) or platform id —
    among those ``connection`` reaches."""
    ref = ref.strip().strip("/")
    if ref.endswith(".git"):
        ref = ref[:-4]
    if not ref:
        raise ValueError("Name a repository, e.g. org/repo.")
    name = ref.rsplit("/", 1)[-1]
    for r in search_repositories(tenant, connection, name, limit=None):
        if r["full_path"].lower() == ref.lower() or str(r["external_id"]) == ref:
            return r
    raise NotFoundError(f"No repository {ref!r} is reachable through {connection.display_name}.")


# --- projects ----------------------------------------------------------------


def get_project(tenant: Tenant, project_id) -> Project:
    try:
        return Project.objects.select_related("platform_connection").get(pk=project_id, tenant=tenant)
    except (Project.DoesNotExist, ValidationError, ValueError):
        raise NotFoundError("Project not found.")


def add_project(
    tenant: Tenant,
    user: User | None,
    connection: PlatformConnection,
    repo: dict,
    *,
    lifecycle: str = Project.Lifecycle.DEVELOPMENT,
    owner: str = "",
    stack_ids=(),
    standard_ids=(),
    critical_ids=(),
) -> AddedProject:
    """Make ``repo`` (a result of ``search_repositories``) a project.

    Attaches the given workspace standards and stacks, reads the repository's
    languages and topics, registers a webhook when the connection needs one
    (GitHub App connections get events through the App), and queues the
    attached runnable standards to run once. ``critical_ids`` marks those
    attachments Critical before anything runs.
    """
    existing = Project.objects.filter(
        tenant=tenant, platform_connection=connection, external_id=str(repo["external_id"])
    ).first()
    if existing:
        raise AlreadyAdded(existing)
    if lifecycle not in Project.Lifecycle.values:
        raise ValueError(
            f"Unknown lifecycle {lifecycle!r}; one of: {', '.join(Project.Lifecycle.values)}."
        )

    project = Project.objects.create(
        tenant=tenant,
        platform_connection=connection,
        platform=connection.platform,
        external_id=str(repo["external_id"]),
        name=repo["name"],
        full_path=repo.get("full_path", ""),
        web_url=repo.get("web_url", ""),
        default_branch=repo.get("default_branch") or "main",
        description=repo.get("description") or "",
        lifecycle=lifecycle,
        owner=owner,
    )
    if stack_ids:
        stacks = Stack.objects.filter(pk__in=list(stack_ids), tenant=tenant)
        stack_service.add_project_to_stacks(tenant=tenant, project=project, stacks=stacks)
    standards = _workspace_standards(tenant, standard_ids)
    project.standards.set(standards)
    set_critical_marks(project, critical_ids)

    _fetch_metadata(project)
    webhook_ok = True
    if connection.auth_method != AuthMethod.GITHUB_APP:
        webhook_ok = register_webhook(project)

    publish(
        ProjectCreated(
            project_id=str(project.id),
            tenant_id=str(tenant.id),
            user_id=str(user.pk) if user else None,
        )
    )
    # After the metadata fetch, so language criteria see real data.
    runs = run_newly_attached(project, standards, previously_attached_ids=set())
    return AddedProject(project=project, webhook_ok=webhook_ok, runs=runs)


def register_webhook(project: Project) -> bool:
    """(Re)register the per-repository webhook. False when the platform refused."""
    connection = project.platform_connection
    try:
        client = get_platform_client(connection)
        if project.webhook_id:
            try:
                client.delete_webhook(project.external_id, project.webhook_id)
            except Exception:
                logger.exception("Failed to delete old webhook for project %s", project.name)
        secret = secrets.token_hex(32)
        target_url = f"{settings.SITE_URL}/api/webhooks/{connection.platform}/"
        project.webhook_id = client.create_webhook(project.external_id, target_url, secret)
        project.webhook_secret = secret
        project.save(update_fields=["webhook_id", "webhook_secret"])
        return True
    except Exception:
        logger.exception("Failed to register webhook for project %s", project.name)
        return False


def update_project(tenant: Tenant, project_id, *, lifecycle: str | None = None, owner: str | None = None) -> Project:
    project = get_project(tenant, project_id)
    fields = []
    if lifecycle is not None:
        if lifecycle not in Project.Lifecycle.values:
            raise ValueError(
                f"Unknown lifecycle {lifecycle!r}; one of: {', '.join(Project.Lifecycle.values)}."
            )
        project.lifecycle = lifecycle
        fields.append("lifecycle")
    if owner is not None:
        project.owner = owner.strip()
        fields.append("owner")
    if fields:
        project.save(update_fields=[*fields, "updated_at"])
    return project


def delete_project(tenant: Tenant, user: User | None, project_id) -> str:
    """Remove the project and its webhook (best effort). Returns its name."""
    project = get_project(tenant, project_id)
    name = project.name
    if project.webhook_id:
        try:
            get_platform_client(project.platform_connection).delete_webhook(
                project.external_id, project.webhook_id
            )
        except Exception:
            logger.exception("Failed to delete webhook for project %s", name)
    pk = str(project.pk)
    project.delete()
    publish(
        ProjectDeleted(
            project_id=pk,
            tenant_id=str(tenant.id),
            project_name=name,
            user_id=str(user.pk) if user else None,
        )
    )
    return name


# --- attached standards ------------------------------------------------------


def set_project_standards(project: Project, standard_ids, critical_ids=None) -> dict:
    """Make exactly ``standard_ids`` the project's attached standards.

    With ``critical_ids``, the Critical marks are rewritten from it before
    anything runs; without, attachments that stay keep their marks.

    Newly attached runnable standards are queued to run. Returns
    ``{"standards", "runs"}``.
    """
    standards = _workspace_standards(project.tenant, standard_ids)
    previously = set(project.standards.values_list("pk", flat=True))
    # set() is a delta: attachments that stay keep their row and its mark.
    project.standards.set(standards)
    if critical_ids is not None:
        set_critical_marks(project, critical_ids)
    return {"standards": standards, "runs": run_newly_attached(project, standards, previously)}


def attach_standards(project: Project, standard_ids) -> dict:
    current = set(project.standards.values_list("pk", flat=True))
    wanted = _workspace_standards(project.tenant, standard_ids)
    return set_project_standards(project, current | {s.pk for s in wanted})


def detach_standards(project: Project, standard_ids) -> dict:
    current = set(project.standards.values_list("pk", flat=True))
    dropped = {s.pk for s in _workspace_standards(project.tenant, standard_ids)}
    return set_project_standards(project, current - dropped)


def run_newly_attached(project: Project, standards, previously_attached_ids) -> dict | None:
    """Queue the newly attached, runnable standards on the project. Returns the
    enqueue summary, or None when nothing new can run."""
    newly_runnable = [
        s for s in standards if s.pk not in previously_attached_ids and s.enabled and not s.draft
    ]
    if not newly_runnable:
        return None
    results = publish(
        StandardsAttached(
            project_id=str(project.pk),
            tenant_id=str(project.tenant_id),
            standard_ids=tuple(str(s.pk) for s in newly_runnable),
        )
    )
    return results[0] if results else None


def set_critical_marks(project: Project, critical_ids) -> None:
    """Write the Critical mark on the project's attachments from
    ``critical_ids``: marked rows get True, every other attachment False.
    Runs after ``standards.set()``, so an id with no surviving attachment
    (a mark on an unattached row) is ignored, as is anything that is not
    an id."""
    critical_ids = _uuids(critical_ids)
    rows = ProjectStandard.objects.filter(project=project)
    rows.exclude(standard_id__in=critical_ids).update(critical=False)
    rows.filter(standard_id__in=critical_ids).update(critical=True)


def _uuids(values) -> list:
    """The values that are UUIDs; anything else is ignored rather than
    failing the query."""
    ids = []
    for value in values:
        try:
            ids.append(uuid.UUID(str(value)))
        except (ValueError, AttributeError, TypeError):
            continue
    return ids


def _workspace_standards(tenant: Tenant, standard_ids) -> list[Standard]:
    ids = [str(i) for i in standard_ids]
    if not ids:
        return []
    try:
        standards = list(Standard.objects.filter(pk__in=ids, tenant=tenant))
    except ValidationError:
        raise NotFoundError("Standard not found.")
    if len(standards) != len(set(ids)):
        raise NotFoundError("Standard not found.")
    return standards


def _fetch_metadata(project: Project) -> None:
    try:
        client = get_platform_client(project.platform_connection)
        project.languages = client.get_languages(project.external_id, full_path=project.full_path)
        project.tags = client.get_topics(project.external_id, full_path=project.full_path)
        project.save(update_fields=["languages", "tags"])
    except Exception:
        logger.exception("Failed to fetch metadata for project %s", project.name)
