"""Public API for a workspace's LLM providers and roles: thin wrappers over
``LLMProviderService``. Owners and admins change them; members read them.
API keys go in and never come out."""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import exceptions, status
from rest_framework.response import Response

from app.application.llm_providers import LLMProviderError, LLMProviderService
from app.domain.models import LLMBudget, LLMProvider, LLMRole
from app.presentation.api import llm_serializers as ls
from app.presentation.api.views import WorkspaceAPIView

_ROLE = OpenApiParameter("role", str, OpenApiParameter.PATH, enum=ls.ROLE_NAMES)


def _provider(p: LLMProvider, roles=None) -> dict:
    if roles is None:
        roles = list(LLMRole.objects.filter(provider=p).values_list("name", flat=True))
    return {
        "id": str(p.pk),
        "provider_type": p.provider_type,
        "display_name": p.display_name,
        "base_url": p.base_url,
        "models": list(p.available_models or []),
        "roles": sorted(roles),
        "created_at": p.created_at.isoformat(),
    }


class LLMAPIView(WorkspaceAPIView):
    def handle_exception(self, exc):
        if isinstance(exc, LLMProviderError):
            exc = exceptions.ValidationError({"detail": str(exc)})
        return super().handle_exception(exc)

    def _get(self, provider_id) -> LLMProvider:
        provider = LLMProvider.objects.filter(tenant=self.tenant, pk=provider_id).first()
        if provider is None:
            raise exceptions.NotFound("Provider not found.")
        return provider


class LLMProvidersView(LLMAPIView):
    @extend_schema(
        operation_id="list_llm_providers",
        tags=["llm"],
        summary="LLM providers and the models each key can use",
        responses={200: ls.LLMProviderSerializer(many=True)},
    )
    def get(self, request, workspace_id):
        roles = {}
        for name, provider_id in LLMRole.objects.filter(tenant=self.tenant).values_list("name", "provider_id"):
            roles.setdefault(provider_id, []).append(name)
        providers = LLMProvider.objects.filter(tenant=self.tenant).order_by("created_at")
        return Response([_provider(p, roles.get(p.pk, [])) for p in providers])

    @extend_schema(
        operation_id="create_llm_provider",
        tags=["llm"],
        summary="Add a provider (owners and admins)",
        description=(
            "Finds the models the key can use. A model runs only once it has an AI budget "
            "(`POST ai/budgets/`) and a role points at it."
        ),
        request=ls.LLMProviderCreateSerializer,
        responses={201: ls.LLMProviderAddedSerializer},
    )
    def post(self, request, workspace_id):
        self.require_admin()
        data = ls.LLMProviderCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        provider, reason = LLMProviderService.add(self.tenant, **data.validated_data)
        return Response({**_provider(provider, []), "note": reason}, status=status.HTTP_201_CREATED)


class LLMProviderView(LLMAPIView):
    @extend_schema(
        operation_id="update_llm_provider",
        tags=["llm"],
        summary="Change a provider's name, endpoint, key or models (owners and admins)",
        request=ls.LLMProviderUpdateSerializer,
        responses={200: ls.LLMProviderSerializer},
    )
    def patch(self, request, workspace_id, provider_id):
        self.require_admin()
        provider = self._get(provider_id)
        data = ls.LLMProviderUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        return Response(_provider(LLMProviderService.edit(provider, **data.validated_data)))

    @extend_schema(
        operation_id="delete_llm_provider",
        tags=["llm"],
        summary="Remove a provider (owners and admins)",
        description="Roles pointing at it are cleared.",
        responses={204: None},
    )
    def delete(self, request, workspace_id, provider_id):
        self.require_admin()
        LLMProviderService.remove(self._get(provider_id))
        return Response(status=status.HTTP_204_NO_CONTENT)


class LLMProviderTestView(LLMAPIView):
    @extend_schema(
        operation_id="test_llm_provider",
        tags=["llm"],
        summary="Check that the provider accepts the key",
        request=None,
        responses={200: ls.LLMProviderTestSerializer},
    )
    def post(self, request, workspace_id, provider_id):
        return Response({"ok": LLMProviderService.test(self._get(provider_id))})


class LLMModelsRefreshView(LLMAPIView):
    @extend_schema(
        operation_id="refresh_llm_models",
        tags=["llm"],
        summary="Find the models the key can use again (owners and admins)",
        request=None,
        responses={200: ls.LLMModelsRefreshSerializer},
    )
    def post(self, request, workspace_id, provider_id):
        self.require_admin()
        models, reason = LLMProviderService.refresh_models(self._get(provider_id))
        return Response({"models": models, "note": reason})


def _roles(tenant) -> list:
    rows = {r.name: r for r in LLMRole.objects.filter(tenant=tenant).select_related("provider")}
    budgeted = set(LLMBudget.objects.filter(tenant=tenant).values_list("provider_id", "model"))
    return [_role(value, label, rows.get(value), budgeted) for value, label in LLMRole.Name.choices]


def _role(value, label, row, budgeted) -> dict:
    return {
        "role": value,
        "label": label,
        "provider": {"id": str(row.provider_id), "name": row.provider.display_name} if row else None,
        "model": row.model if row else None,
        "has_budget": bool(row) and (row.provider_id, row.model) in budgeted,
    }


class LLMRolesView(LLMAPIView):
    @extend_schema(
        operation_id="list_llm_roles",
        tags=["llm"],
        summary="Which provider and model GitGrit uses for each kind of work",
        responses={200: ls.LLMRoleSerializer(many=True)},
    )
    def get(self, request, workspace_id):
        return Response(_roles(self.tenant))


class LLMRoleView(LLMAPIView):
    @extend_schema(
        operation_id="set_llm_role",
        tags=["llm"],
        summary="Point a role at a provider and model (owners and admins)",
        parameters=[_ROLE],
        request=ls.LLMRoleSetSerializer,
        responses={200: ls.LLMRoleSerializer},
    )
    def put(self, request, workspace_id, role):
        self.require_admin()
        data = ls.LLMRoleSetSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        LLMProviderService.set_role(self.tenant, role, **data.validated_data)
        return Response(next(r for r in _roles(self.tenant) if r["role"] == role))

    @extend_schema(
        operation_id="clear_llm_role",
        tags=["llm"],
        summary="Clear a role (owners and admins)",
        parameters=[_ROLE],
        responses={204: None},
    )
    def delete(self, request, workspace_id, role):
        self.require_admin()
        LLMProviderService.set_role(self.tenant, role)
        return Response(status=status.HTTP_204_NO_CONTENT)
