"""Artifact projects: projects whose files arrive as archives, not from Git.

Any project can be one: its files are a build (a built web app's dist, a
bundle, a release package) rather than a repository. Each upload is a
commit, in Git's terms: a SHA (the archive's content hash), a message, a
branch and an author. A person uploads commits from the project page, or
another system does it through the API with a workspace token: it creates
the artifact project (idempotent on its own id for it, in a stack found by
name) and uploads each new build as a commit. Each commit is checked as a push:
a ``push`` event on its branch, pinned to its SHA, so the standards that run
on pushes check it and the existing commit endpoints report its results.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils.text import slugify

from app.application import stack_service
from app.application.commit_checks import forget_platform_lists
from app.application.errors import NotFoundError
from app.application.standard_engine import StandardEngine
from app.application.standard_runs import enqueue_run
from app.domain.models import (
    Platform,
    PlatformConnection,
    Project,
    Stack,
    Standard,
    ArtifactCommit,
)
from app.domain.artifacts import (
    DEFAULT_LIMITS,
    TreeNode,
    UploadRejected,
    commit_sha,
    file_tree,
    languages_from_paths,
)
from app.infrastructure import archives, upload_storage

# An upload is a push: the same standards run on it.
PUSH_EVENT = "push"
ARTIFACT_CONNECTION_NAME = "Artifacts"


def artifact_connection(tenant) -> PlatformConnection:
    """The workspace's one artifact connection, created on first use. It
    holds no credentials: it only groups the workspace's artifact projects the
    way a Git connection groups repositories."""
    try:
        with transaction.atomic():
            connection, _ = PlatformConnection.objects.get_or_create(
                tenant=tenant,
                platform=Platform.ARTIFACT,
                defaults={"display_name": ARTIFACT_CONNECTION_NAME, "base_url": ""},
            )
    except IntegrityError:  # created concurrently (one per workspace)
        connection = PlatformConnection.objects.get(tenant=tenant, platform=Platform.ARTIFACT)
    return connection


def _stack_named(tenant, name: str) -> Stack:
    stack = Stack.objects.filter(tenant=tenant, name=name).order_by("created_at").first()
    return stack or stack_service.create_stack(tenant=tenant, name=name)


@dataclass
class CreatedProject:
    project: Project
    created: bool


def create_artifact_project(
    tenant,
    *,
    name: str,
    external_id: str,
    stack: str = "",
    description: str = "",
    standard_ids: list | None = None,
) -> CreatedProject:
    """Find or create the artifact project the caller knows as ``external_id``.

    A new project gets its root component in ``stack`` (found by name, or
    created) and the standards named by ``standard_ids`` (none by default, as
    for a repository). An existing project is returned as it is, so the call
    is safe to repeat.
    """
    name, external_id = name.strip(), external_id.strip()
    if not name or not external_id:
        raise ValueError("A project needs a name and an external_id.")
    connection = artifact_connection(tenant)
    existing = Project.objects.filter(
        tenant=tenant, platform_connection=connection, external_id=external_id
    ).first()
    if existing:
        return CreatedProject(existing, created=False)

    standards = list(Standard.objects.filter(tenant=tenant, pk__in=standard_ids or []))
    if len(standards) != len(set(map(str, standard_ids or []))):
        raise NotFoundError("Standard not found.")

    try:
        with transaction.atomic():
            project = Project.objects.create(
                tenant=tenant,
                platform_connection=connection,
                platform=Platform.ARTIFACT,
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


def create_manual_artifact_project(
    tenant, *, name: str, stack: str = "", description: str = ""
) -> Project:
    """An artifact project someone creates by hand in the web app. Nothing
    outside GitGrit knows it, so it gets an id of its own."""
    return create_artifact_project(
        tenant,
        name=name,
        external_id=f"manual-{uuid.uuid4().hex}",
        stack=stack,
        description=description,
    ).project


def get_artifact_project(tenant, project_id) -> Project:
    project = Project.objects.filter(
        tenant=tenant, pk=project_id, platform=Platform.ARTIFACT
    ).first()
    if project is None:
        raise NotFoundError("Artifact project not found.")
    return project


@dataclass
class UploadedCommit:
    commit: ArtifactCommit
    created: bool
    run: dict | None  # the enqueue summary; None when no standard applies


def upload_commit(
    project: Project,
    data: bytes,
    *,
    message: str = "",
    branch: str = "",
    user=None,
    author: str = "",
    limits=DEFAULT_LIMITS,
) -> UploadedCommit:
    """Store ``data`` as a commit of ``project`` on ``branch`` (the project's
    default branch when empty) and queue the standards that run on pushes
    to that branch, as for a pushed commit.

    The archive is checked against the upload rules before anything is
    stored (``UploadRejected`` otherwise). The same bytes uploaded again are
    the same commit: nothing new is stored, but the standards run again, as
    pushing it again would run them.
    """
    if not project.is_artifact:
        raise ValueError(f"{project.name} is not an artifact project.")
    manifest = archives.scan(data, limits)
    sha = commit_sha(data)
    branch = branch.strip() or project.default_branch
    key = upload_storage.archive_key(project.tenant_id, project.pk, sha)
    upload_storage.save_archive(key, data)

    with transaction.atomic():
        commit, created = ArtifactCommit.objects.get_or_create(
            project=project,
            sha=sha,
            defaults={
                "message": message.strip(),
                "branch": branch,
                "archive_key": key,
                "size": len(data),
                "file_count": len(manifest.paths),
                "author": author,
                "author_user": user,
            },
        )
        languages = languages_from_paths(manifest.paths)
        if languages != project.languages:
            project.languages = languages
            project.save(update_fields=["languages", "updated_at"])

        standards = StandardEngine().get_standards_for_project(
            project, PUSH_EVENT, ref=branch
        )
        run = enqueue_run(
            project,
            standards,
            event_type=PUSH_EVENT,
            triggered_by=author,
            user=user,
            ref=branch,
            commit_sha=sha,
            committed_at=commit.created_at,
            skip_running=False,
        )
    # Like a push: the project page must not keep showing the commit list it
    # cached before this upload.
    forget_platform_lists([project])
    return UploadedCommit(commit=commit, created=created, run=run)


def commit_dict(commit: ArtifactCommit) -> dict:
    return {
        "sha": commit.sha,
        "message": commit.message,
        "branch": commit.branch,
        "author": commit.author,
        "size": commit.size,
        "file_count": commit.file_count,
        "created_at": commit.created_at.isoformat(),
    }


def upload_result_dict(result: UploadedCommit) -> dict:
    """What the upload call answers: the commit, and what was queued on it.
    Poll its checks at ``.../commits/<sha>/`` until ``running`` is 0."""
    run = result.run or {"queued": 0, "already_running": 0, "executions": []}
    return {
        "commit": commit_dict(result.commit),
        "created": result.created,
        "queued": run["queued"],
        "message": run.get("message") or "No standard runs on pushes to this branch.",
    }


# --- Browsing a commit's files ----------------------------------------------


def get_commit(project: Project, sha: str = "") -> ArtifactCommit | None:
    """The uploaded commit with ``sha``, or the newest one when ``sha`` is
    empty. None when there is no such commit."""
    commits = project.artifact_commits.order_by("-created_at")
    return commits.filter(sha=sha).first() if sha else commits.first()


def commit_tree(commit: ArtifactCommit) -> TreeNode:
    """The commit's folders and files, as the sandbox sees them."""
    data = upload_storage.read_archive(commit.archive_key)
    return file_tree(archives.scan(data).sizes)


def commit_file(commit: ArtifactCommit, path: str) -> bytes | None:
    """One file of the commit, or None when it has no such file."""
    return archives.read_file(upload_storage.read_archive(commit.archive_key), path)


def commit_archive(commit: ArtifactCommit) -> tuple[bytes, str]:
    """The commit's archive as uploaded, and a file name for downloading it."""
    data = upload_storage.read_archive(commit.archive_key)
    return data, f"{slugify(commit.project.name) or 'project'}-{commit.sha[:7]}{archives.archive_extension(data)}"
