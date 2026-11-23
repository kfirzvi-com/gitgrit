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
from app.domain import importance
from app.domain.events import ProjectCreated, ProjectDeleted, StandardsAttached
from app.domain.projects import InvalidRootPath, RootPath
from app.domain.projects.languages import languages_in
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
    """The repository (at that root path) is already a project in this workspace."""

    def __init__(self, project: Project):
        super().__init__(
            f'"{project.repository_label or project.name}" is already a project in this workspace.'
        )
        self.project = project


@dataclass(frozen=True)
class AddedProject:
    project: Project
    webhook_ok: bool  # False when a per-repo webhook was needed and couldn't be registered
    runs: dict | None  # the first run's enqueue summary, None when nothing was queued


# --- connections -------------------------------------------------------------


def _git_connections(tenant: Tenant):
    """The workspace's Git platform connections. The artifact connection is
    left out: it holds no credentials, reaches no repositories, and deleting
    it would delete every artifact project."""
    return PlatformConnection.objects.filter(tenant=tenant).exclude(platform=Platform.ARTIFACT)


def list_connections(tenant: Tenant) -> list[PlatformConnection]:
    return list(_git_connections(tenant).order_by("created_at"))


def get_connection(tenant: Tenant, connection_id) -> PlatformConnection:
    try:
        return _git_connections(tenant).get(id=connection_id)
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
    ``query``. Each lists ``added_paths``, the root paths it is already a
    project at here (``""`` = the whole repository), and is marked
    ``already_added`` when the whole repository is one. A repository with
    projects at some paths can still be added at another."""
    try:
        results = get_platform_client(connection).search_projects(query.strip())
    except Exception as exc:
        logger.exception("Failed to search repositories on connection %s", connection.pk)
        raise PlatformError("Couldn't search the git platform. Check the connection.") from exc
    added: dict[str, list[str]] = {}
    for external_id, root_path in Project.objects.filter(
        tenant=tenant, platform_connection=connection
    ).values_list("external_id", "root_path"):
        added.setdefault(external_id, []).append(root_path)
    for r in results:
        paths = sorted(added.get(str(r["external_id"]), []))
        r["added_paths"] = paths
        r["already_added"] = "" in paths
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
    root_path: str = "",
    lifecycle: str = Project.Lifecycle.DEVELOPMENT,
    owner: str = "",
    stack_ids=(),
    standard_ids=(),
    importances=None,
) -> AddedProject:
    """Make ``repo`` (a result of ``search_repositories``) a project, rooted
    at ``root_path`` inside it ("" = the whole repository; a monorepo holds
    one project per app or service). Raises ``InvalidRootPath`` on a path
    that leaves the repository.

    Attaches the given workspace standards and stacks, reads the repository's
    languages and topics, registers a webhook when the connection needs one
    (GitHub App connections get events through the App), and queues the
    attached runnable standards to run once. ``importances`` (standard id
    -> importance) sets those attached standards' importance.
    """
    location = RootPath.parse(root_path)
    if location.value and connection.platform == Platform.ARTIFACT:
        raise InvalidRootPath("An artifact project always covers its whole upload.")
    existing = Project.objects.filter(
        tenant=tenant,
        platform_connection=connection,
        external_id=str(repo["external_id"]),
        root_path=location.value,
    ).first()
    if existing:
        raise AlreadyAdded(existing)
    if lifecycle not in Project.Lifecycle.values:
        raise ValueError(
            f"Unknown lifecycle {lifecycle!r}; one of: {', '.join(Project.Lifecycle.values)}."
        )
    if importances is not None:
        importances = parse_importances(importances)

    project = Project.objects.create(
        tenant=tenant,
        platform_connection=connection,
        platform=connection.platform,
        external_id=str(repo["external_id"]),
        name=project_name(repo["name"], location),
        full_path=repo.get("full_path", ""),
        root_path=location.value,
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
    if importances:
        ProjectStandard.set_importances(project, importances)

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


def project_name(repo_name: str, location: RootPath) -> str:
    """A new project's name: the repository's, then its root path inside it
    (``shop/apps/web``), so projects sharing a repository stay apart."""
    return f"{repo_name}/{location.value}" if location.value else repo_name


def _repository_siblings(project: Project):
    """The other projects on the same repository through the same connection."""
    return Project.objects.filter(
        platform_connection=project.platform_connection, external_id=project.external_id
    ).exclude(pk=project.pk)


def register_webhook(project: Project) -> bool:
    """(Re)register the per-repository webhook. False when the platform refused.

    A repository has one webhook however many projects sit in it: a project
    added next to others shares their hook (every delivery is routed to all
    the repository's projects), so a push is never delivered twice."""
    connection = project.platform_connection
    shared = _repository_siblings(project).exclude(webhook_id="").first()
    if shared and not project.webhook_id:
        project.webhook_id = shared.webhook_id
        project.webhook_secret = shared.webhook_secret
        project.save(update_fields=["webhook_id", "webhook_secret"])
        return True
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
        # Re-registering replaced the hook its siblings shared.
        _repository_siblings(project).exclude(webhook_id="").update(
            webhook_id=project.webhook_id, webhook_secret=secret
        )
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
    """Remove the project, and its webhook (best effort) unless another
    project on the same repository still uses it. Returns its name."""
    project = get_project(tenant, project_id)
    name = project.name
    hook_shared = _repository_siblings(project).filter(webhook_id=project.webhook_id).exists()
    if project.webhook_id and not hook_shared:
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


def set_project_standards(project: Project, standard_ids, importances=None) -> dict:
    """Make exactly ``standard_ids`` the project's attached standards.

    ``importances`` (standard id -> importance) sets the importance of those
    attached standards; attached standards it leaves out keep theirs.
    Newly attached runnable standards are queued to run. Returns
    ``{"standards", "runs"}``.
    """
    if importances is not None:
        importances = parse_importances(importances)
    standards = _workspace_standards(project.tenant, standard_ids)
    previously = set(project.standards.values_list("pk", flat=True))
    # set() is a delta: attached standards that stay keep their row and importance.
    project.standards.set(standards)
    if importances:
        ProjectStandard.set_importances(project, importances)
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


def set_importance(project: Project, standard_id, value) -> ProjectStandard:
    """Set one attached standard's importance on the project. Raises
    ``UnknownImportance`` on a value that names none, and ``NotFoundError``
    when the standard is not attached to the project."""
    chosen = importance.parse(value)
    try:
        attachment = ProjectStandard.objects.select_related("standard").get(
            project=project, standard_id=standard_id
        )
    except (ProjectStandard.DoesNotExist, ValidationError, ValueError):
        raise NotFoundError("That standard is not attached to this project.")
    ProjectStandard.set_importances(project, {attachment.standard_id: chosen})
    attachment.importance = chosen.value
    return attachment


def parse_importances(importances: dict) -> dict:
    """``importances`` (standard id -> posted value) as standard id ->
    ``Importance``. Raises ``UnknownImportance`` (a ``ValueError``) on a value
    that names none, before anything is written. An id that is not a UUID
    names no standard and is dropped."""
    parsed = {}
    for standard_id, value in importances.items():
        try:
            key = str(uuid.UUID(str(standard_id)))
        except ValueError:
            continue
        parsed[key] = importance.parse(value)
    return parsed


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
        project.languages = _languages(client, project)
        project.tags = client.get_topics(project.external_id, full_path=project.full_path)
        project.save(update_fields=["languages", "tags"])
    except Exception:
        logger.exception("Failed to fetch metadata for project %s", project.name)


def _languages(client, project: Project) -> list[str]:
    """The platform's languages for a whole-repository project; counted from
    the files under the root path for one inside a repository (the platforms
    only report languages per repository)."""
    if not project.root_path:
        return client.get_languages(project.external_id, full_path=project.full_path)
    location = project.location
    files = [p for p in client.get_tree(project.full_path, project.default_branch) if location.contains(p)]
    return languages_in(files)
