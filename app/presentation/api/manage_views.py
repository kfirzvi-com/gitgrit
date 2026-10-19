"""Public API for setting a workspace up: connections, repositories, projects,
attached standards and the marketplace.

Thin wrappers over ``project_management``, ``marketplace_service`` and
``StandardService`` — the same services the web views use — so the CLI and
the browser stay in step. Connections are for owners and admins; everything
else is open to any member and to workspace tokens.
"""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.response import Response

from app.application import marketplace_service
from app.application import project_management as pm
from app.application.errors import NotFoundError
from app.application.standard_service import StandardService
from app.domain.models import AuthMethod, MarketplacePack, MarketplaceStandard, Project
from app.presentation.api import serializers as s
from app.presentation.api import views
from app.presentation.api.views import ProjectListView, WorkspaceAPIView

_standards = StandardService()


# --- presenters ---------------------------------------------------------------


def _connection(c) -> dict:
    return {
        "id": str(c.id),
        "display_name": c.display_name,
        "platform": c.platform,
        "auth_method": c.auth_method,
        "base_url": c.base_url or "",
        "account_login": c.account_login,
        "created_at": c.created_at.isoformat(),
    }


def _attached(standard) -> dict:
    return {
        "id": str(standard.id),
        "name": standard.name,
        "enabled": standard.enabled,
        "draft": standard.draft,
    }


def _project(p: Project) -> dict:
    if p.platform_connection.auth_method == AuthMethod.GITHUB_APP:
        webhook = "app"
    else:
        webhook = "active" if p.webhook_id else "missing"
    return {
        "id": str(p.id),
        "name": p.name,
        "description": p.description,
        "platform": p.platform,
        "full_path": p.full_path,
        "web_url": p.web_url,
        "default_branch": p.default_branch,
        "lifecycle": p.lifecycle,
        "languages": p.languages or [],
        "tags": p.tags or [],
        "owner": p.owner,
        "connection_id": str(p.platform_connection_id),
        "webhook": webhook,
        "standards": [_attached(x) for x in p.standards.order_by("ordinal", "name")],
    }


def _installed(standard, created: bool) -> dict:
    return {"id": str(standard.id), "name": standard.name, "created": created}


def _marketplace_standard(mp: MarketplaceStandard, installed: dict) -> dict:
    copy = installed.get(mp.slug)
    return {
        "slug": mp.slug,
        "name": mp.name,
        "description": mp.description,
        "version": mp.version,
        "labels": list(mp.suggested_labels or []),
        "installed_standard_id": str(copy.id) if copy else None,
        "update_available": marketplace_service.update_available(copy, mp),
    }


def _pack(pack: MarketplacePack, installed: dict) -> dict:
    return {
        "slug": pack.slug,
        "name": pack.name,
        "description": pack.description,
        "icon": pack.icon,
        "standards": [
            _marketplace_standard(mp, installed) for mp in sorted(pack.standards.all(), key=lambda m: m.name)
        ],
    }


# --- connections & repositories ----------------------------------------------


class ConnectionListView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_connections",
        tags=["connections"],
        summary="List git platform connections",
        description="Tokens are never returned.",
        responses=s.ConnectionSerializer(many=True),
    )
    def get(self, request, **_):
        return Response([_connection(c) for c in pm.list_connections(self.tenant)])

    @extend_schema(
        operation_id="create_connection",
        tags=["connections"],
        summary="Connect a platform with an access token",
        description=(
            "Owners and admins only. For GitHub, the GitHub App is recommended "
            "instead: install it from workspace settings in the browser."
        ),
        request=s.ConnectionCreateSerializer,
        responses={201: s.ConnectionSerializer},
    )
    def post(self, request, **_):
        self.require_admin()
        body = s.ConnectionCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        connection = pm.add_token_connection(
            self.tenant,
            data["platform"],
            data["access_token"],
            display_name=data["display_name"],
            base_url=data["base_url"],
        )
        return Response(_connection(connection), status=status.HTTP_201_CREATED)


class RepositoryListView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_repositories",
        tags=["connections"],
        summary="Repositories a connection can reach",
        description="Up to 25, filtered by `q` (matched against `org/repo`). 502 when the platform refuses.",
        parameters=[OpenApiParameter("q", str, required=False)],
        responses=s.RepositorySerializer(many=True),
    )
    def get(self, request, connection_id, **_):
        connection = pm.get_connection(self.tenant, connection_id)
        return Response(
            pm.search_repositories(self.tenant, connection, request.query_params.get("q", ""))
        )


# --- projects -----------------------------------------------------------------


class ProjectsView(ProjectListView):
    """The projects collection: listing (inherited) and adding."""

    @extend_schema(
        operation_id="create_project",
        tags=["projects"],
        summary="Add a repository as a project",
        description=(
            "Registers a webhook unless the connection is a GitHub App, reads the "
            "repository's languages, and queues the attached standards to run once. "
            "409 when it's already a project."
        ),
        request=s.ProjectCreateSerializer,
        responses={201: s.ProjectCreatedSerializer},
    )
    def post(self, request, **_):
        body = s.ProjectCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        connection, repo = self._locate(data["repository"], data.get("connection_id"))
        added = pm.add_project(
            self.tenant,
            self.actor,
            connection,
            repo,
            lifecycle=data["lifecycle"],
            owner=data["owner"],
            standard_ids=data["standards"],
        )
        return Response(
            {**_project(added.project), "runs": added.runs}, status=status.HTTP_201_CREATED
        )

    def _locate(self, ref, connection_id):
        """The connection and repository ``ref`` names: in the given
        connection, or in the only one that reaches it."""
        if connection_id:
            connection = pm.get_connection(self.tenant, connection_id)
            return connection, pm.find_repository(self.tenant, connection, ref)
        connections = pm.list_connections(self.tenant)
        if not connections:
            raise ValueError("Connect a git platform first.")
        found, failed = [], None
        for connection in connections:
            try:
                found.append((connection, pm.find_repository(self.tenant, connection, ref)))
            except NotFoundError:
                continue
            except pm.PlatformError as exc:
                failed = exc
        if len(found) == 1:
            return found[0]
        if len(found) > 1:
            names = ", ".join(c.display_name for c, _ in found)
            raise ValueError(f"{ref!r} is reachable through several connections ({names}); pass connection_id.")
        if failed:
            raise failed
        raise NotFoundError(f"No connection reaches a repository {ref!r}.")


class ProjectDetailView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_project",
        tags=["projects"],
        summary="Get a project with its attached standards",
        description="Every attached standard, including drafts and disabled ones, which don't run.",
        responses=s.ProjectDetailSerializer,
    )
    def get(self, request, project_id, **_):
        return Response(_project(pm.get_project(self.tenant, project_id)))

    @extend_schema(
        operation_id="update_project",
        tags=["projects"],
        summary="Update a project's lifecycle or owner",
        description="Only the fields sent change.",
        request=s.ProjectUpdateSerializer,
        responses=s.ProjectDetailSerializer,
    )
    def patch(self, request, project_id, **_):
        body = s.ProjectUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        project = pm.update_project(self.tenant, project_id, **body.validated_data)
        return Response(_project(project))

    @extend_schema(
        operation_id="delete_project",
        tags=["projects"],
        summary="Remove a project",
        description="Also removes its webhook from the platform (best effort).",
        responses={204: None},
    )
    def delete(self, request, project_id, **_):
        pm.delete_project(self.tenant, self.actor, project_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProjectStandardsView(views.ProjectStandardsView):
    """A project's standards: the active ones (inherited), attaching, detaching."""

    @extend_schema(
        operation_id="attach_project_standards",
        tags=["projects"],
        summary="Attach standards to a project",
        description="Newly attached, enabled standards are queued to run on it.",
        request=s.StandardIdsSerializer,
        responses=s.ProjectStandardsChangeSerializer,
    )
    def post(self, request, project_id, **_):
        return self._change(request, project_id, pm.attach_standards)

    def _change(self, request, project_id, change):
        body = s.StandardIdsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return _changed(change(pm.get_project(self.tenant, project_id), body.validated_data["standards"]))


class ProjectStandardView(WorkspaceAPIView):
    @extend_schema(
        operation_id="detach_project_standard",
        tags=["projects"],
        summary="Detach a standard from a project",
        description="Its past results stay; it just stops running on the project.",
        responses={200: s.ProjectStandardsChangeSerializer},
    )
    def delete(self, request, project_id, standard_id, **_):
        project = pm.get_project(self.tenant, project_id)
        return _changed(pm.detach_standards(project, [standard_id]))


def _changed(result) -> Response:
    return Response({"standards": [_attached(x) for x in result["standards"]], "runs": result["runs"]})


# --- standards on/off ---------------------------------------------------------


class StandardEnableView(WorkspaceAPIView):
    enabled = True

    @extend_schema(
        operation_id="enable_standard",
        tags=["standards"],
        summary="Turn a standard on",
        description="Queues it on every project it's attached to. 400 for a draft.",
        request=None,
        responses=s.StandardEnabledSerializer,
    )
    def post(self, request, standard_id, **_):
        return Response(
            _standards.set_enabled(self.tenant, self.actor, str(standard_id), self.enabled)
        )


class StandardDisableView(StandardEnableView):
    enabled = False

    @extend_schema(
        operation_id="disable_standard",
        tags=["standards"],
        summary="Turn a standard off",
        description="It stops running everywhere; its attachments stay.",
        request=None,
        responses=s.StandardEnabledSerializer,
    )
    def post(self, request, standard_id, **_):
        return super().post(request, standard_id)


# --- marketplace --------------------------------------------------------------


class MarketplaceView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_marketplace",
        tags=["marketplace"],
        summary="Browse the marketplace",
        description="Every pack and standard, with this workspace's install state.",
        responses=s.MarketplaceSerializer,
    )
    def get(self, request, **_):
        installed = marketplace_service.installed_by_slug(self.tenant)
        return Response(
            {
                "packs": [
                    _pack(p, installed)
                    for p in MarketplacePack.objects.prefetch_related("standards").order_by("name")
                ],
                "standards": [
                    _marketplace_standard(mp, installed)
                    for mp in MarketplaceStandard.objects.order_by("name")
                ],
            }
        )


class MarketplacePackView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_marketplace_pack",
        tags=["marketplace"],
        summary="A pack and its standards",
        description="Each standard carries this workspace's install state.",
        responses=s.MarketplacePackSerializer,
    )
    def get(self, request, slug, **_):
        pack = marketplace_service.get_pack(slug)
        return Response(_pack(pack, marketplace_service.installed_by_slug(self.tenant)))


class MarketplacePackInstallView(WorkspaceAPIView):
    @extend_schema(
        operation_id="install_marketplace_pack",
        tags=["marketplace"],
        summary="Install every standard in a pack",
        description="Standards the workspace already has are skipped. Installed standards are enabled but attached to no project.",
        request=None,
        responses=s.PackInstallSerializer,
    )
    def post(self, request, slug, **_):
        result = marketplace_service.install_pack(self.tenant, self.actor, slug)
        return Response(
            {
                "pack": result["pack"].slug,
                "installed": [_installed(x, True) for x in result["installed"]],
                "skipped": [_installed(x, False) for x in result["skipped"]],
            }
        )


class MarketplaceStandardInstallView(WorkspaceAPIView):
    @extend_schema(
        operation_id="install_marketplace_standard",
        tags=["marketplace"],
        summary="Install one marketplace standard",
        description="Returns the existing copy, with `created: false`, when already installed.",
        request=None,
        responses=s.InstalledStandardSerializer,
    )
    def post(self, request, slug, **_):
        standard, created = marketplace_service.install_standard(self.tenant, self.actor, slug)
        return Response(_installed(standard, created))


class MarketplaceStandardUpdateView(WorkspaceAPIView):
    @extend_schema(
        operation_id="update_marketplace_standard",
        tags=["marketplace"],
        summary="Update an installed standard to the marketplace's latest version",
        description="The new version is queued on every project it's attached to.",
        request=None,
        responses=s.MarketplaceUpdateSerializer,
    )
    def post(self, request, slug, **_):
        standard, runs = marketplace_service.update_standard(self.tenant, self.actor, slug)
        return Response(
            {
                "id": str(standard.id),
                "name": standard.name,
                "version": standard.source_version,
                "runs": runs,
            }
        )
