import re

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.utils.text import slugify
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, TemplateView

from app.domain.models import (
    LLMProvider,
    LLMProviderType,
    LLMRole,
    Membership,
    Platform,
    PlatformConnection,
    Tenant,
)
from app.infrastructure.llm_models import discover_models, test_provider
from app.infrastructure.platform_client import get_platform_client

User = get_user_model()


@login_required
@require_POST
def switch_tenant(request):
    tenant_id = request.POST.get("tenant_id")
    membership = Membership.objects.filter(
        user=request.user, tenant_id=tenant_id
    ).first()
    if membership:
        request.session["active_tenant_id"] = str(membership.tenant_id)
    return redirect("dashboard")


class CreateTenantView(LoginRequiredMixin, CreateView):
    model = Tenant
    fields = ["name"]
    template_name = "pages/create_tenant.html"

    def form_valid(self, form):
        base_slug = slugify(form.cleaned_data["name"])
        slug = base_slug
        counter = 1
        while Tenant.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{counter}"
            counter += 1

        tenant = Tenant.objects.create(
            name=form.cleaned_data["name"],
            slug=slug,
        )
        Membership.objects.create(
            user=self.request.user, tenant=tenant, role=Membership.Role.OWNER
        )
        self.request.session["active_tenant_id"] = str(tenant.id)
        messages.success(self.request, f'Workspace "{tenant.name}" created.')
        return redirect("dashboard")


class TenantSettingsView(LoginRequiredMixin, TemplateView):
    template_name = "pages/tenant_settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        if tenant:
            context["members"] = (
                Membership.objects.filter(tenant=tenant)
                .select_related("user")
                .order_by("created_at")
            )
            context["connections"] = PlatformConnection.objects.filter(
                tenant=tenant
            ).order_by("created_at")
            context["platform_choices"] = Platform.choices

            # LLM configuration
            llm_providers = list(
                LLMProvider.objects.filter(tenant=tenant).order_by("created_at")
            )
            context["llm_providers"] = llm_providers
            context["llm_provider_types"] = LLMProviderType.choices
            existing_roles = {
                r.name: r
                for r in LLMRole.objects.filter(tenant=tenant).select_related(
                    "provider"
                )
            }
            context["llm_role_rows"] = [
                {
                    "name": value,
                    "label": label,
                    "provider_id": (
                        str(existing_roles[value].provider_id)
                        if value in existing_roles
                        else ""
                    ),
                    "model": (
                        existing_roles[value].model if value in existing_roles else ""
                    ),
                }
                for value, label in LLMRole.Name.choices
            ]
            # provider id -> available models, consumed by the role dropdown JS
            context["llm_provider_models_map"] = {
                str(p.id): list(p.available_models or []) for p in llm_providers
            }

            user_membership = Membership.objects.filter(
                user=self.request.user, tenant=tenant
            ).first()
            context["is_admin"] = user_membership and user_membership.role in (
                Membership.Role.OWNER,
                Membership.Role.ADMIN,
            )
        return context


@login_required
@require_POST
def invite_member(request):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    user_membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not user_membership or user_membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        messages.error(request, "You don't have permission to invite members.")
        return redirect("tenant_settings")

    email = request.POST.get("email", "").strip()
    role = request.POST.get("role", Membership.Role.MEMBER)
    if role not in (Membership.Role.ADMIN, Membership.Role.MEMBER):
        role = Membership.Role.MEMBER

    invitee = User.objects.filter(email=email).first()
    if not invitee:
        messages.error(request, f"No user found with email {email}.")
        return redirect("tenant_settings")

    if Membership.objects.filter(user=invitee, tenant=tenant).exists():
        messages.warning(request, f"{email} is already a member.")
        return redirect("tenant_settings")

    Membership.objects.create(user=invitee, tenant=tenant, role=role)
    messages.success(request, f"{email} added as {role}.")
    return redirect("tenant_settings")


@login_required
@require_POST
def remove_member(request, membership_id):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    user_membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not user_membership or user_membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        messages.error(request, "You don't have permission to remove members.")
        return redirect("tenant_settings")

    target = get_object_or_404(Membership, id=membership_id, tenant=tenant)

    if target.role == Membership.Role.OWNER:
        messages.error(request, "Cannot remove the workspace owner.")
        return redirect("tenant_settings")

    target.delete()
    messages.success(request, "Member removed.")
    return redirect("tenant_settings")


@login_required
@require_POST
def add_connection(request):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    user_membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not user_membership or user_membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        messages.error(request, "You don't have permission to manage connections.")
        return redirect("tenant_settings")

    platform = request.POST.get("platform", "")
    display_name = request.POST.get("display_name", "").strip()
    base_url = request.POST.get("base_url", "").strip()
    access_token = request.POST.get("access_token", "").strip()

    if not access_token:
        messages.error(request, "Access token is required.")
        return redirect("tenant_settings")

    if platform not in (Platform.GITHUB, Platform.GITLAB):
        messages.error(request, "Invalid platform.")
        return redirect("tenant_settings")

    if not display_name:
        platform_labels = {Platform.GITHUB: "GitHub", Platform.GITLAB: "GitLab"}
        base_name = platform_labels[platform]
        existing_names = set(
            PlatformConnection.objects.filter(tenant=tenant).values_list(
                "display_name", flat=True
            )
        )
        if base_name not in existing_names:
            display_name = base_name
        else:
            n = 2
            while f"{base_name} {n}" in existing_names:
                n += 1
            display_name = f"{base_name} {n}"

    connection = PlatformConnection(
        tenant=tenant,
        platform=platform,
        display_name=display_name,
        base_url=base_url,
        access_token=access_token,
    )
    connection.save()
    messages.success(request, f'Connection "{display_name}" added.')
    return redirect("tenant_settings")


@login_required
@require_POST
def edit_connection_token(request, connection_id):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    user_membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not user_membership or user_membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        messages.error(request, "You don't have permission to manage connections.")
        return redirect("tenant_settings")

    connection = get_object_or_404(PlatformConnection, id=connection_id, tenant=tenant)
    access_token = request.POST.get("access_token", "").strip()

    if not access_token:
        messages.error(request, "Access token is required.")
        return redirect("tenant_settings")

    connection.access_token = access_token
    connection.save(update_fields=["access_token"])
    messages.success(request, f'Token updated for "{connection.display_name}".')
    return redirect("tenant_settings")


@login_required
@require_POST
def reveal_connection_token(request, connection_id):
    """Return the decrypted access token for an authorised admin/owner.

    The token is a secret and is deliberately never rendered into the settings
    page. The edit-token modal's "Show" control calls this endpoint so the
    token only crosses the wire on an explicit, authenticated, CSRF-protected
    request — never sitting in the page source.
    """
    from django.http import JsonResponse

    tenant = request.tenant
    if not tenant:
        return JsonResponse({"error": "No active workspace."}, status=400)

    membership = Membership.objects.filter(user=request.user, tenant=tenant).first()
    if not membership or membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        return JsonResponse(
            {"error": "You don't have permission to manage connections."},
            status=403,
        )

    connection = get_object_or_404(PlatformConnection, id=connection_id, tenant=tenant)
    return JsonResponse({"token": connection.access_token})


@login_required
@require_POST
def remove_connection(request, connection_id):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    user_membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not user_membership or user_membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        messages.error(request, "You don't have permission to manage connections.")
        return redirect("tenant_settings")

    connection = get_object_or_404(PlatformConnection, id=connection_id, tenant=tenant)
    name = connection.display_name
    connection.delete()
    messages.success(request, f'Connection "{name}" removed.')
    return redirect("tenant_settings")


@login_required
@require_POST
def test_connection(request, connection_id):
    from django.http import HttpResponse

    tenant = request.tenant
    if not tenant:
        return HttpResponse('<span class="badge badge-error">No workspace</span>')

    connection = get_object_or_404(PlatformConnection, id=connection_id, tenant=tenant)
    try:
        client = get_platform_client(connection)
        if client.test_token():
            return HttpResponse('<span class="badge badge-success">Connected</span>')
        else:
            return HttpResponse(
                '<span class="badge badge-error">Invalid token</span>'
            )
    except Exception:
        return HttpResponse(
            '<span class="badge badge-error">Connection failed</span>'
        )


# --- LLM providers & roles -------------------------------------------------


def _require_workspace_admin(request):
    """Return (tenant, None) when the user may manage workspace settings, else
    (tenant, redirect) bouncing them back to settings with a message."""
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return None, redirect("tenant_settings")
    membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not membership or membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        messages.error(
            request, "You don't have permission to manage workspace settings."
        )
        return tenant, redirect("tenant_settings")
    return tenant, None


def _auto_provider_name(tenant, provider_type) -> str:
    label = dict(LLMProviderType.choices).get(provider_type, provider_type)
    existing = set(
        LLMProvider.objects.filter(tenant=tenant).values_list(
            "display_name", flat=True
        )
    )
    if label not in existing:
        return label
    n = 2
    while f"{label} {n}" in existing:
        n += 1
    return f"{label} {n}"


@login_required
@require_POST
def add_llm_provider(request):
    tenant, deny = _require_workspace_admin(request)
    if deny:
        return deny

    provider_type = request.POST.get("provider_type", "")
    display_name = request.POST.get("display_name", "").strip()
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()

    if provider_type not in LLMProviderType.values:
        messages.error(request, "Invalid provider type.")
        return redirect("tenant_settings")
    if not api_key:
        messages.error(request, "API key is required.")
        return redirect("tenant_settings")

    if not display_name:
        display_name = _auto_provider_name(tenant, provider_type)

    models = discover_models(provider_type, base_url, api_key)
    provider = LLMProvider(
        tenant=tenant,
        provider_type=provider_type,
        display_name=display_name,
        base_url=base_url,
        api_key=api_key,
        available_models=models,
    )
    provider.save()

    if models:
        messages.success(
            request,
            f'Provider "{display_name}" added — discovered {len(models)} models.',
        )
    else:
        messages.warning(
            request,
            f'Provider "{display_name}" added, but no models could be '
            f"auto-detected. Add them manually via Edit.",
        )
    return redirect("tenant_settings")


@login_required
@require_POST
def edit_llm_provider(request, provider_id):
    tenant, deny = _require_workspace_admin(request)
    if deny:
        return deny

    provider = get_object_or_404(LLMProvider, id=provider_id, tenant=tenant)
    display_name = request.POST.get("display_name", "").strip()
    base_url = request.POST.get("base_url", "").strip()
    api_key = request.POST.get("api_key", "").strip()
    models_text = request.POST.get("models", "")

    if display_name:
        provider.display_name = display_name
    provider.base_url = base_url
    if api_key:
        provider.api_key = api_key

    manual = [m.strip() for m in re.split(r"[\n,]", models_text) if m.strip()]
    if manual:
        provider.available_models = manual

    provider.save()
    messages.success(request, f'Provider "{provider.display_name}" updated.')
    return redirect("tenant_settings")


@login_required
@require_POST
def remove_llm_provider(request, provider_id):
    tenant, deny = _require_workspace_admin(request)
    if deny:
        return deny

    provider = get_object_or_404(LLMProvider, id=provider_id, tenant=tenant)
    name = provider.display_name
    provider.delete()  # cascades to any roles pointing at it
    messages.success(request, f'Provider "{name}" removed.')
    return redirect("tenant_settings")


@login_required
@require_POST
def test_llm_provider(request, provider_id):
    from django.http import HttpResponse

    tenant = request.tenant
    if not tenant:
        return HttpResponse('<span class="badge badge-error">No workspace</span>')

    provider = get_object_or_404(LLMProvider, id=provider_id, tenant=tenant)
    if test_provider(provider.provider_type, provider.base_url, provider.api_key):
        return HttpResponse('<span class="badge badge-success">Connected</span>')
    return HttpResponse('<span class="badge badge-error">Failed</span>')


@login_required
@require_POST
def fetch_llm_models(request, provider_id):
    from django.http import HttpResponse

    tenant = request.tenant
    if not tenant:
        return HttpResponse('<span class="badge badge-error">No workspace</span>')
    membership = Membership.objects.filter(
        user=request.user, tenant=tenant
    ).first()
    if not membership or membership.role not in (
        Membership.Role.OWNER,
        Membership.Role.ADMIN,
    ):
        return HttpResponse('<span class="badge badge-error">Forbidden</span>')

    provider = get_object_or_404(LLMProvider, id=provider_id, tenant=tenant)
    models = discover_models(provider.provider_type, provider.base_url, provider.api_key)
    if models:
        provider.available_models = models
        provider.save(update_fields=["available_models"])
        return HttpResponse(
            f'<span class="badge badge-success">{len(models)} models — '
            f"reload to use</span>"
        )
    return HttpResponse('<span class="badge badge-warning">none found</span>')


@login_required
@require_POST
def set_llm_role(request, role_name):
    tenant, deny = _require_workspace_admin(request)
    if deny:
        return deny

    if role_name not in LLMRole.Name.values:
        messages.error(request, "Invalid role.")
        return redirect("tenant_settings")

    provider_id = request.POST.get("provider_id", "").strip()
    model = request.POST.get("model", "").strip()

    if not provider_id:
        LLMRole.objects.filter(tenant=tenant, name=role_name).delete()
        messages.success(request, f'Cleared the "{role_name}" role.')
        return redirect("tenant_settings")

    provider = get_object_or_404(LLMProvider, id=provider_id, tenant=tenant)
    if not model:
        messages.error(request, "Select a model for the role.")
        return redirect("tenant_settings")

    LLMRole.objects.update_or_create(
        tenant=tenant,
        name=role_name,
        defaults={"provider": provider, "model": model},
    )
    messages.success(
        request, f'Role "{role_name}" set to {provider.display_name}/{model}.'
    )
    return redirect("tenant_settings")
