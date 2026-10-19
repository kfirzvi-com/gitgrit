"""Upload projects in the web app: creating one by hand, uploading a version
from the project page, and browsing a version's files.

A version's files are untrusted: a game studio built them. They are only
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
from django.views.decorators.http import require_POST

from app.application import upload_service
from app.domain.models import Platform, Project, Stack
from app.domain.uploads import DEFAULT_LIMITS, UploadRejected
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


def _upload_project(request, pk) -> Project:
    return get_object_or_404(Project, pk=pk, tenant=request.tenant, platform=Platform.UPLOAD)


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
def add_upload_project(request):
    """Create an upload project by hand, optionally with its first version."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("project_list")
    stacks = Stack.objects.filter(tenant=tenant).order_by("name")
    form = {"name": "", "stack": "", "description": "", "label": ""}
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
            project = upload_service.create_manual_upload_project(
                tenant, name=form["name"], stack=form["stack"], description=form["description"]
            )
            if data is not None:
                try:
                    upload_service.upload_version(
                        project, data, label=form["label"],
                        user=request.user, uploaded_by=request.user.username,
                    )
                except UploadRejected as exc:
                    messages.warning(request, f'Created "{project.name}", but its archive was rejected: {exc}')
                    return redirect("project_detail", pk=project.pk)
                messages.success(request, f'Created "{project.name}" and queued its first version.')
                return redirect(reverse("project_detail", args=[project.pk]) + "#results")
            messages.success(request, f'Created "{project.name}". Upload its first version.')
            return redirect("project_detail", pk=project.pk)
    return render(
        request,
        "pages/add_upload_project.html",
        {"stacks": stacks, "form": form, "error": error},
    )


@login_required
@require_POST
def upload_project_version(request, pk):
    """The project page's Upload version dialog (HTMX). On success the
    dialog closes and the Results tab, the overview card and the Files tab
    reload in place (the ``versionUploaded`` event)."""
    project = _upload_project(request, pk)
    label = request.POST.get("label", "").strip()
    channel = request.POST.get("channel", "").strip()
    try:
        result = upload_service.upload_version(
            project, _archive_from(request), label=label, channel=channel,
            user=request.user, uploaded_by=request.user.username,
        )
    except UploadRejected as exc:
        return render(
            request,
            "partials/upload_version_form.html",
            {"project": project, "error": str(exc), "label": label, "channel": channel},
        )
    version = result.version
    response = render(request, "partials/upload_version_form.html", {"project": project})
    response["HX-Trigger"] = json.dumps(
        {"versionUploaded": {"digest": version.digest, "channel": version.channel}}
    )
    name = version.label or version.digest[:7]
    text = (
        f"Uploaded {name}: {result.run['message']}" if result.run
        else f"Uploaded {name}. No standard runs on uploads to {version.channel}."
    )
    if not result.created:
        text = f"{name} was uploaded before; checking it again."
    return toast(response, text)


@login_required
def project_overview_health(request, pk):
    """The Overview tab's health card on its own, so an upload can refresh it."""
    project = _upload_project(request, pk)
    return render(
        request,
        "partials/project_overview_health.html",
        {"project": project, **results_context(project)},
    )


@login_required
def project_files(request, pk):
    """The Files tab: a version picker, the version's folder tree and, when
    ``path`` names a file, that file."""
    project = _upload_project(request, pk)
    versions = list(project.versions.order_by("-created_at"))
    version = upload_service.get_version(project, request.GET.get("version", ""))
    context = {"project": project, "versions": versions, "version": version}
    path = request.GET.get("path", "")
    if version is not None and path:
        context["file"] = _file_view(project, version, path)
        if request.headers.get("HX-Target") == "file-view":
            return render(request, "partials/file_view.html", context)
    if version is not None:
        context["tree"] = upload_service.version_tree(version)
    return render(request, "partials/project_files.html", context)


def _file_view(project, version, path: str) -> dict:
    content = upload_service.version_file(version, path)
    view = {"path": path, "missing": content is None}
    if content is None:
        return view
    view["size"] = len(content)
    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    if extension in IMAGE_TYPES:
        query = urlencode({"version": version.digest, "path": path})
        view["image_url"] = f'{reverse("project_file_raw", args=[project.pk])}?{query}'
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
def project_file_raw(request, pk):
    """One image of a version, for the Files tab's preview. Nothing else is
    served raw (see the module docstring)."""
    project = _upload_project(request, pk)
    path = request.GET.get("path", "")
    extension = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    content_type = IMAGE_TYPES.get(extension)
    version = upload_service.get_version(project, request.GET.get("version", ""))
    if content_type is None or version is None:
        raise Http404
    content = upload_service.version_file(version, path)
    if content is None:
        raise Http404
    response = HttpResponse(content, content_type=content_type)
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "sandbox; default-src 'none'"
    response["Content-Disposition"] = "inline"
    return response

