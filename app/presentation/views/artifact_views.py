"""Artifact projects in the web app: creating one by hand, uploading a commit
from the project page, and browsing a commit's files.

A commit's files are untrusted: whoever uploaded them built them. They are only
ever shown as escaped text inside GitGrit's own pages; the one raw endpoint
serves raster images, under a sandboxing CSP, and never HTML, SVG or
script, so nothing uploaded runs on GitGrit's origin.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from app.application import artifact_service
from app.domain.models import Platform, Project, Stack
from app.domain.artifacts import DEFAULT_LIMITS, UploadRejected
from app.presentation.htmx import toast
from app.presentation.views.project_views import results_context

# Shown as text up to this size; past it the viewer says how big it is.
TEXT_PREVIEW_BYTES = 512 * 1024
# Raster images only: an SVG can carry script.
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
}


def _artifact_project(request, pk) -> Project:
    return get_object_or_404(Project, pk=pk, tenant=request.tenant, platform=Platform.ARTIFACT)


def _archive_from(request):
    """The uploaded archive's bytes, or raise ``UploadRejected``."""
    archive = request.FILES.get("archive")
    if archive is None:
        raise UploadRejected("Choose a .zip or .tar.gz archive to upload.")
    limit = DEFAULT_LIMITS.max_archive_bytes
    if archive.size > limit:
        raise UploadRejected(f"Archive is larger than {limit // (1024 * 1024)} MB.")
    return archive.read()


@login_required
def add_artifact_project(request):
    """Create an artifact project by hand, optionally with its first commit."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")
    stacks = Stack.objects.filter(tenant=tenant).order_by("name")
    form = {"name": "", "stack": "", "description": "", "message": ""}
    error = ""
    if request.method == "POST":
        form = {key: request.POST.get(key, "").strip() for key in form}
        data = None
        try:
            if not form["name"]:
                raise UploadRejected("Give the project a name.")
            if request.FILES.get("archive"):
                data = _archive_from(request)
        except UploadRejected as exc:
            error = str(exc)
        if not error:
            project = artifact_service.create_manual_artifact_project(
                tenant, name=form["name"], stack=form["stack"], description=form["description"]
            )
            if data is not None:
                try:
                    artifact_service.upload_commit(
                        project, data, message=form["message"],
                        user=request.user, author=request.user.username,
                    )
                except UploadRejected as exc:
                    messages.warning(request, f'Created "{project.name}", but its archive was rejected: {exc}')
                    return redirect("project_detail", pk=project.pk)
                messages.success(request, f'Created "{project.name}" and queued its first commit.')
                return redirect(reverse("project_detail", args=[project.pk]) + "#results")
            messages.success(request, f'Created "{project.name}". Upload its first commit.')
            return redirect("project_detail", pk=project.pk)
    return render(
        request,
        "pages/add_artifact_project.html",
        {"stacks": stacks, "form": form, "error": error},
    )


@login_required
@require_POST
def upload_project_commit(request, pk):
    """The project page's Upload commit dialog (HTMX). On success the dialog
    closes and the Results tab and the overview card reload in place (the
    ``commitUploaded`` event)."""
    project = _artifact_project(request, pk)
    message = request.POST.get("message", "").strip()
    branch = request.POST.get("branch", "").strip()
    try:
        result = artifact_service.upload_commit(
            project, _archive_from(request), message=message, branch=branch,
            user=request.user, author=request.user.username,
        )
    except UploadRejected as exc:
        return render(
            request,
            "partials/upload_commit_form.html",
            {"project": project, "error": str(exc), "message": message, "branch": branch},
        )
    commit = result.commit
    response = render(request, "partials/upload_commit_form.html", {"project": project})
    response["HX-Trigger"] = json.dumps(
        {"commitUploaded": {"sha": commit.sha, "branch": commit.branch}}
    )
    short = commit.sha[:7]
    if not result.created:
        text = f"{short} was uploaded before; checking it again."
    elif result.run:
        text = f"Uploaded {short}: {result.run['message']}"
    else:
        text = f"Uploaded {short}. No standard runs on uploads to {commit.branch}."
    return toast(response, text)


@login_required
def project_overview_health(request, pk):
    """The Overview tab's health card on its own, so an upload can refresh it."""
    project = _artifact_project(request, pk)
    return render(
        request,
        "partials/project_overview_health.html",
        {"project": project, **results_context(project)},
    )


@login_required
def commit_files(request, pk):
    """One uploaded commit's files, for the modal the Results tab opens from
    a commit's SHA: its folder tree and, when ``path`` names a file, that
    file. A request aimed at the viewer (``HX-Target: file-view``) gets just
    the file."""
    project = _artifact_project(request, pk)
    commit = artifact_service.get_commit(project, request.GET.get("sha", ""))
    if commit is None:
        raise Http404
    context = {"project": project, "commit": commit}
    path = request.GET.get("path", "")
    if path:
        context["file"] = _file_view(project, commit, path)
        if request.headers.get("HX-Target") == "file-view":
            return render(request, "partials/file_view.html", context)
    context["tree"] = artifact_service.commit_tree(commit)
    return render(request, "partials/commit_files.html", context)


def _file_view(project, commit, path: str) -> dict:
    content = artifact_service.commit_file(commit, path)
    view = {"path": path, "missing": content is None}
    if content is None:
        return view
    view["size"] = len(content)
    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if extension in IMAGE_TYPES:
        query = urlencode({"sha": commit.sha, "path": path})
        view["image_url"] = f'{reverse("commit_file_raw", args=[project.pk])}?{query}'
        return view
    try:
        text = content[:TEXT_PREVIEW_BYTES].decode("utf-8")
    except UnicodeDecodeError:
        view["binary"] = True
        return view
    view["text"] = text
    view["truncated"] = len(content) > TEXT_PREVIEW_BYTES
    view["lines"] = text.count("\n") + 1
    view["longest_line"] = max((len(line) for line in text.splitlines()), default=0)
    return view


@login_required
def commit_file_raw(request, pk):
    """One image of an uploaded commit, for the file viewer's preview.
    Nothing else is served raw (see the module docstring)."""
    project = _artifact_project(request, pk)
    path = request.GET.get("path", "")
    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    content_type = IMAGE_TYPES.get(extension)
    commit = artifact_service.get_commit(project, request.GET.get("sha", ""))
    if content_type is None or commit is None:
        raise Http404
    content = artifact_service.commit_file(commit, path)
    if content is None:
        raise Http404
    response = HttpResponse(content, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["Content-Disposition"] = "inline"
    return response


@login_required
def commit_download(request, pk):
    """Download an uploaded commit: the whole archive, or the one file
    ``path`` names. Always an attachment the browser saves, never a page it
    renders, so it is safe for any file type."""
    project = _artifact_project(request, pk)
    commit = artifact_service.get_commit(project, request.GET.get("sha", ""))
    if commit is None:
        raise Http404
    path = request.GET.get("path", "")
    if path:
        content = artifact_service.commit_file(commit, path)
        if content is None:
            raise Http404
        filename = path.rsplit("/", 1)[-1]
    else:
        content, filename = artifact_service.commit_archive(commit)
    response = HttpResponse(content, content_type="application/octet-stream")
    response["Content-Disposition"] = content_disposition_header(True, filename)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    return response
