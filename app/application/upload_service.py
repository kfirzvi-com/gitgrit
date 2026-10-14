"""Upload projects: projects whose files arrive as archives, not from Git.

The use case they serve: a platform that hosts other people's builds (e.g. a
web gaming platform receiving each studio's game dist) checks every upload
against the workspace's standards. The platform calls the API with a
workspace token: it creates one stack per studio and one upload project per
game (idempotent on the platform's own game id), then uploads each new
build as a version. Each version is checked like a pushed commit: an
``upload`` event on the version's channel, pinned to the version's digest,
so the existing commit endpoints report its results.
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction

from app.application import stack_service
from app.application.errors import NotFoundError
from app.application.standard_engine import StandardEngine
from app.application.standard_runs import enqueue_run
from app.domain.models import (
    Platform,
    PlatformConnection,
    Project,
    ProjectVersion,
    Stack,
    Standard,
)
from app.domain.uploads import DEFAULT_LIMITS, UploadRejected, content_digest, languages_from_paths
from app.infrastructure import archives, upload_storage

UPLOAD_EVENT = "upload"
UPLOAD_CONNECTION_NAME = "Uploads"


def upload_connection(tenant) -> PlatformConnection:
    """The workspace's one upload connection, created on first use. It
    holds no credentials: it only groups the workspace's upload projects the
    way a Git connection groups repositories."""
    try:
        with transaction.atomic():
            connection, _ = PlatformConnection.objects.get_or_create(
                tenant=tenant,
                platform=Platform.UPLOAD,
                defaults={"display_name": UPLOAD_CONNECTION_NAME, "base_url": ""},
            )
    except IntegrityError:  # created concurrently (one per workspace)
        connection = PlatformConnection.objects.get(tenant=tenant, platform=Platform.UPLOAD)
    return connection


def _stack_named(tenant, name: str) -> Stack:
    stack = Stack.objects.filter(tenant=tenant, name=name).order_by("created_at").first()
    return stack or stack_service.create_stack(tenant=tenant, name=name)


def _default_standards(tenant):
    """What a new upload project is checked against when the caller names
    no standards: every live, enabled, published standard that runs on
    uploads."""
    return [
        s
        for s in Standard.objects.filter(tenant=tenant, enabled=True, draft=False)
        if UPLOAD_EVENT in (s.criteria or {}).get("events", [])
    ]


@dataclass
class CreatedProject:
    project: Project
    created: bool


def create_upload_project(
    tenant,
    *,
    name: str,
    external_id: str,
    stack: str = "",
    description: str = "",
    standard_ids: list | None = None,
) -> CreatedProject:
    """Find or create the upload project the caller knows as ``external_id``.

    A new project gets its root component in ``stack`` (found by name, or
    created) and the standards named by ``standard_ids``, or by default every
    published standard that runs on uploads. An existing project is returned
    as it is, so the call is safe to repeat.
    """
    name, external_id = name.strip(), external_id.strip()
    if not name or not external_id:
        raise ValueError("A project needs a name and an external_id.")
    connection = upload_connection(tenant)
    existing = Project.objects.filter(
        tenant=tenant, platform_connection=connection, external_id=external_id
    ).first()
    if existing:
        return CreatedProject(existing, created=False)

    if standard_ids is None:
        standards = _default_standards(tenant)
    else:
        standards = list(Standard.objects.filter(tenant=tenant, pk__in=standard_ids))
        if len(standards) != len(set(map(str, standard_ids))):
            raise NotFoundError("Standard not found.")

    try:
        with transaction.atomic():
            project = Project.objects.create(
                tenant=tenant,
                platform_connection=connection,
                platform=Platform.UPLOAD,
                external_id=external_id,
                name=name,
                full_path=name,
                web_url="",
                description=description,
            )
            if stack.strip():
                stack_service.add_project_to_stacks(
                    tenant=tenant, project=project, stacks=[_stack_named(tenant, stack.strip())]
                )
            project.standards.set(standards)
    except IntegrityError:
        # Lost a race with an identical request: return what it created.
        return CreatedProject(
            Project.objects.get(
                tenant=tenant, platform_connection=connection, external_id=external_id
            ),
            created=False,
        )
    return CreatedProject(project, created=True)


def get_upload_project(tenant, project_id) -> Project:
    project = Project.objects.filter(
        tenant=tenant, pk=project_id, platform=Platform.UPLOAD
    ).first()
    if project is None:
        raise NotFoundError("Upload project not found.")
    return project


@dataclass
class UploadedVersion:
    version: ProjectVersion
    created: bool
    run: dict | None  # the enqueue summary; None when no standard applies


def upload_version(
    project: Project,
    data: bytes,
    *,
    label: str = "",
    channel: str = "",
    user=None,
    uploaded_by: str = "",
    limits=DEFAULT_LIMITS,
) -> UploadedVersion:
    """Store ``data`` as a version of ``project`` and queue the standards that
    run on uploads to its ``channel`` (the project's default one when empty).

    The archive is checked against the upload rules before anything is
    stored (``UploadRejected`` otherwise). The same bytes uploaded again are
    the same version: nothing new is stored, but the standards run again, as
    a repeated push would run them.
    """
    if not project.is_upload:
        raise ValueError(f"{project.name} is not an upload project.")
    manifest = archives.scan(data, limits)
    digest = content_digest(data)
    channel = channel.strip() or project.default_branch
    key = upload_storage.archive_key(project.tenant_id, project.pk, digest)
    upload_storage.save_archive(key, data)

    with transaction.atomic():
        version, created = ProjectVersion.objects.get_or_create(
            project=project,
            digest=digest,
            defaults={
                "label": label.strip(),
                "channel": channel,
                "archive_key": key,
                "size": len(data),
                "file_count": len(manifest.paths),
                "uploaded_by": uploaded_by,
                "uploaded_by_user": user,
            },
        )
        languages = languages_from_paths(manifest.paths)
        if languages != project.languages:
            project.languages = languages
            project.save(update_fields=["languages", "updated_at"])

        standards = StandardEngine().get_standards_for_project(
            project, UPLOAD_EVENT, ref=channel
        )
        run = enqueue_run(
            project,
            standards,
            event_type=UPLOAD_EVENT,
            triggered_by=uploaded_by,
            user=user,
            ref=channel,
            commit_sha=digest,
            committed_at=version.created_at,
            skip_running=False,
        )
    return UploadedVersion(version=version, created=created, run=run)



def version_dict(version: ProjectVersion) -> dict:
    return {
        "id": str(version.id),
        "digest": version.digest,
        "label": version.label,
        "channel": version.channel,
        "size": version.size,
        "file_count": version.file_count,
        "uploaded_by": version.uploaded_by,
        "created_at": version.created_at.isoformat(),
    }


def list_versions(project: Project) -> list[dict]:
    """Every version of the project, newest first (versions are kept forever)."""
    return [version_dict(v) for v in project.versions.order_by("-created_at")]


def upload_result_dict(result: UploadedVersion) -> dict:
    """What the upload call answers: the version, and what was queued on it.
    Poll the version's checks at ``.../commits/<digest>/`` until ``running``
    is 0."""
    run = result.run or {"queued": 0, "already_running": 0, "executions": []}
    return {
        "version": version_dict(result.version),
        "created": result.created,
        "queued": run["queued"],
        "message": run.get("message") or "No standard runs on uploads to this channel.",
    }
