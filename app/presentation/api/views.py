"""Public REST API views: thin wrappers over the application services."""
from django.conf import settings
from drf_spectacular.utils import OpenApiParameter, extend_schema
from oauth2_provider.contrib.rest_framework import OAuth2Authentication
from rest_framework import exceptions, status
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from app.application.project_health_service import ProjectHealthService
from app.application.errors import NotFoundError
from app.application.project_service import ProjectService, SandboxService
from app.application.project_status_service import ProjectStatusService
from app.application.standard_service import StandardService
from app.domain.models import APIToken, Membership
from app.presentation.api import serializers as s
from app.presentation.api.authentication import APITokenAuthentication, HasToken, ReadWriteScope

_projects = ProjectService()
_status = ProjectStatusService()
_standards = StandardService()
_sandbox = SandboxService()
_health = ProjectHealthService()

_BRANCH = OpenApiParameter("branch", str, required=False)


def server_version() -> str:
    """The release tag, else the short commit, else "dev" (local runs)."""
    return settings.GIT_TAG or settings.GIT_SHA[:7] or "dev"


class PublicAPIView(APIView):
    """Bearer-authenticated: an OAuth access token or a ``grit_`` token.

    JSON in and out. Every response carries ``X-GitGrit-Version`` so clients
    (the CLI) can tell which server they talk to.
    """

    authentication_classes = [APITokenAuthentication, OAuth2Authentication]
    permission_classes = [HasToken, ReadWriteScope]
    parser_classes = [JSONParser]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["X-GitGrit-Version"] = server_version()
        return response

    @property
    def actor(self):
        """The user acting, recorded on what the call changes; None for a
        workspace token."""
        user = self.request.user
        return user if user.is_authenticated else None

    @property
    def workspace_token(self) -> APIToken | None:
        auth = self.request.auth
        if isinstance(auth, APIToken) and auth.kind == APIToken.Kind.WORKSPACE:
            return auth
        return None


class WorkspaceAPIView(PublicAPIView):
    """Scoped to the workspace named in the URL.

    A user (OAuth or personal token) must be a member of it; a workspace token
    reaches only its own workspace. Anything else is a 404, so workspace ids
    cannot be probed. Service errors map onto HTTP: a tenant-scoped miss is
    404, any other ``ValueError`` (e.g. standard code without ``evaluate``)
    is 400.
    """

    tenant = None

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        self.tenant = self._workspace(kwargs["workspace_id"])

    def _workspace(self, workspace_id):
        token = self.workspace_token
        if token is not None:
            if token.tenant_id == workspace_id:
                return token.tenant
        else:
            membership = (
                Membership.objects.filter(user=self.request.user, tenant_id=workspace_id)
                .select_related("tenant")
                .first()
            )
            if membership:
                return membership.tenant
        raise exceptions.NotFound("Workspace not found.")

    def handle_exception(self, exc):
        if isinstance(exc, NotFoundError):
            exc = exceptions.NotFound(str(exc))
        elif isinstance(exc, ValueError):
            exc = exceptions.ValidationError({"detail": str(exc)})
        return super().handle_exception(exc)


class MeView(PublicAPIView):
    @extend_schema(
        operation_id="get_me",
        tags=["auth"],
        summary="Who am I",
        description=(
            "What the token acts as and the workspaces it can reach: every workspace "
            "the user belongs to for an OAuth or personal token; just its own, with "
            "no user, for a workspace token."
        ),
        responses=s.MeSerializer,
    )
    def get(self, request):
        auth = request.auth
        if isinstance(auth, APIToken):
            token_type = f"{auth.kind}_token"
        else:
            token_type = "oauth"
        token = self.workspace_token
        if token is not None:
            return Response(
                {
                    "token_type": token_type,
                    "user": None,
                    "workspaces": [
                        {"id": str(token.tenant.id), "name": token.tenant.name, "role": None}
                    ],
                }
            )
        user = request.user
        memberships = Membership.objects.filter(user=user).select_related("tenant")
        return Response(
            {
                "token_type": token_type,
                "user": {"id": str(user.pk), "username": user.username, "email": user.email},
                "workspaces": [
                    {"id": str(m.tenant.id), "name": m.tenant.name, "role": m.role}
                    for m in memberships.order_by("tenant__name")
                ],
            }
        )


class ProjectListView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_projects",
        tags=["projects"],
        summary="List projects",
        responses=s.ProjectSerializer(many=True),
    )
    def get(self, request, **_):
        return Response(_projects.list_projects(self.tenant))


class ProjectResolveView(WorkspaceAPIView):
    @extend_schema(
        operation_id="resolve_project",
        tags=["projects"],
        summary="Resolve a git remote to a project",
        description=(
            "Pass `repo_full_path` (e.g. `acme/backend`) and/or `web_url` — raw "
            "`git remote get-url origin` output is accepted. A miss returns 404 "
            "with up to 5 close candidates."
        ),
        parameters=[
            OpenApiParameter("repo_full_path", str, required=False),
            OpenApiParameter("web_url", str, required=False),
        ],
        responses={200: s.ResolvedProjectSerializer, 404: s.ProjectNotFoundSerializer},
    )
    def get(self, request, **_):
        result = _projects.resolve_project(
            self.tenant,
            request.query_params.get("repo_full_path"),
            request.query_params.get("web_url"),
        )
        if "error" in result:
            return Response(
                {"detail": "No project matches.", "candidates": result["candidates"]},
                status=status.HTTP_404_NOT_FOUND,
            )
        return Response(result)


class ProjectStatusView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_project_status",
        tags=["projects"],
        summary="Compliance grade and top offenders",
        responses=s.ProjectStatusSerializer,
    )
    def get(self, request, project_id, **_):
        return Response(_status.get_project_status(self.tenant, str(project_id)))


class ProjectStandardsView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_project_standards",
        tags=["projects"],
        summary="Active standards attached to a project",
        description="Each carries the extracted `rules` used for local enforcement.",
        responses=s.ActiveStandardSerializer(many=True),
    )
    def get(self, request, project_id, **_):
        return Response(_standards.list_active_for_project(self.tenant, str(project_id)))


class StandardListView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_standards",
        tags=["standards"],
        summary="List standards",
        responses=s.StandardSummarySerializer(many=True),
    )
    def get(self, request, **_):
        return Response(_standards.list_standards(self.tenant))

    @extend_schema(
        operation_id="create_standard",
        tags=["standards"],
        summary="Create a standard",
        description="An active standard attached to projects is queued to run on save.",
        request=s.StandardCreateSerializer,
        responses={201: s.StandardMutationSerializer},
    )
    def post(self, request, **_):
        body = s.StandardCreateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = {**body.validated_data, "change_summary": "Created via API"}
        result = _standards.create_standard(self.tenant, self.actor, data)
        result.pop("created", None)
        return Response(result, status=status.HTTP_201_CREATED)


class StandardDetailView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_standard",
        tags=["standards"],
        summary="Get a standard with its code and recent executions",
        responses=s.StandardDetailSerializer,
    )
    def get(self, request, standard_id, **_):
        return Response(_standards.get_standard(self.tenant, str(standard_id)))

    @extend_schema(
        operation_id="update_standard",
        tags=["standards"],
        summary="Update a standard",
        description=(
            "Only the fields sent change; every save is versioned. Drafts are "
            "always disabled — to publish, send `draft: false, enabled: true`."
        ),
        request=s.StandardUpdateSerializer,
        responses=s.StandardMutationSerializer,
    )
    def patch(self, request, standard_id, **_):
        body = s.StandardUpdateSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        result = _standards.update_standard(
            self.tenant, self.actor, str(standard_id), body.validated_data
        )
        result.pop("updated", None)
        return Response(result)

    @extend_schema(
        operation_id="delete_standard",
        tags=["standards"],
        summary="Delete a standard",
        responses={204: None},
    )
    def delete(self, request, standard_id, **_):
        _standards.delete_standard(self.tenant, str(standard_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class StandardTestView(WorkspaceAPIView):
    @extend_schema(
        operation_id="test_standard",
        tags=["standards"],
        summary="Dry-run standard code against mock project data",
        description="Runs in the gVisor sandbox; nothing is saved.",
        request=s.StandardTestSerializer,
        responses=s.StandardTestResultSerializer,
    )
    def post(self, request, **_):
        body = s.StandardTestSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return Response(
            _sandbox.run_standard_test(
                body.validated_data["code"], body.validated_data["mock_input"]
            )
        )


class ProjectBranchesView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_project_branches",
        tags=["health"],
        summary="List a project's branches",
        description="The default branch first. Read from the Git platform.",
        responses=s.BranchSerializer(many=True),
    )
    def get(self, request, project_id, **_):
        return Response(_health.branches(self.tenant, str(project_id)))


class ProjectHealthView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_project_health",
        tags=["health"],
        summary="Project or branch health",
        description=(
            "Without `branch`: the project's health — each attached standard's "
            "latest result on its home branch (the default branch unless the "
            "standard's filter names one). With `branch`: that branch's health. "
            "Levels: healthy ≥ 80, warning ≥ 50, critical below."
        ),
        parameters=[_BRANCH],
        responses=s.ProjectHealthSerializer,
    )
    def get(self, request, project_id, **_):
        return Response(
            _health.health(self.tenant, str(project_id), request.query_params.get("branch"))
        )


class ProjectCommitsView(WorkspaceAPIView):
    @extend_schema(
        operation_id="list_project_commits",
        tags=["health"],
        summary="A branch's commits with their checks",
        description=(
            "Newest first, 5 per page, from the Git platform (falls back to the "
            "commits GitGrit checked). Unchecked commits have empty `results`."
        ),
        parameters=[_BRANCH, OpenApiParameter("page", int, required=False)],
        responses=s.CommitPageSerializer,
    )
    def get(self, request, project_id, **_):
        try:
            page = max(1, int(request.query_params.get("page") or 1))
        except ValueError:
            raise exceptions.ValidationError({"page": "Must be a positive integer."})
        return Response(
            _health.commits(
                self.tenant, str(project_id), request.query_params.get("branch"), page
            )
        )


class ProjectCommitView(WorkspaceAPIView):
    @extend_schema(
        operation_id="get_project_commit",
        tags=["health"],
        summary="One commit's checks",
        description=(
            "From what GitGrit recorded; 404 when the commit was never checked. "
            "Poll this after `run_project_check` until `running` is 0."
        ),
        responses=s.CommitSerializer,
    )
    def get(self, request, project_id, sha, **_):
        return Response(_health.commit(self.tenant, str(project_id), sha))


class ProjectCheckView(WorkspaceAPIView):
    @extend_schema(
        operation_id="run_project_check",
        tags=["health"],
        summary="Check a commit now",
        description=(
            "Runs the standards that apply to the branch, in the background, on "
            "one commit or on the branch's latest commit. Standards already "
            "running are left alone."
        ),
        request=s.RunCheckSerializer,
        responses={202: s.RunCheckResultSerializer},
    )
    def post(self, request, project_id, **_):
        body = s.RunCheckSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        result = _health.run(
            self.tenant,
            self.actor,
            str(project_id),
            body.validated_data.get("branch"),
            body.validated_data["sha"],
        )
        return Response(result, status=status.HTTP_202_ACCEPTED)
