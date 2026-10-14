import re

from django.conf import settings
from django import forms
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils.html import escape
from django.views.decorators.http import require_POST
from django.views.generic import FormView, TemplateView
from django_htmx.http import HttpResponseClientRedirect

from app.application import membership_service
from app.application.event_bus import publish
from app.application.workspace_service import (
    can_delete_workspace,
    create_workspace,
    delete_workspace,
)
from app.domain.events import MemberJoined, MemberRemoved
from app.domain.models import (
    APIToken,
    LLMProvider,
    LLMProviderType,
    LLMRole,
    Membership,
    Platform,
    PlatformConnection,
    Tenant,
)
from app.infrastructure.llm_models import discover, test_provider
from app.infrastructure.platform_client import get_platform_client
from app.workspace_access import (
    enter_support_view,
    has_admin_membership,
    is_workspace_admin,
    leave_support_view,
    parse_tenant_id,
)

User = get_user_model()


@login_required
@require_POST
def switch_tenant(request):
    """Make ``tenant_id`` the active workspace.

    Members switch into their own workspaces. A superuser may also switch into
    any other workspace: that is the support view, timestamped in the session
    so the middleware trusts the id, and logged.
    """
    tenant_id = parse_tenant_id(request.POST.get("tenant_id"))
    membership = (
        Membership.objects.filter(user=request.user, tenant_id=tenant_id).first()
        if tenant_id
        else None
    )
    if membership:
        leave_support_view(request)
        request.session["active_tenant_id"] = str(membership.tenant_id)
    elif tenant_id and request.user.is_superuser:
        tenant = Tenant.objects.filter(id=tenant_id).first()
        if tenant:
            enter_support_view(request, tenant)
    if request.htmx:
        return HttpResponseClientRedirect(reverse("dashboard"))
    return redirect("dashboard")


@login_required
@require_POST
def leave_support_view_view(request):
    """The banner's "back to my workspace" button. Drops the support view; the
    middleware then lands the user in their own first workspace."""
    leave_support_view(request)
    if request.htmx:
        return HttpResponseClientRedirect(reverse("dashboard"))
    return redirect("dashboard")


@login_required
@require_POST
def leave_workspace(request):
    """Drop the user's own membership in the current workspace.

    The last remaining owner can't leave: the workspace would be orphaned.
    Members and admins can always leave.
    """
    tenant = request.tenant
    membership = (
        Membership.objects.filter(user=request.user, tenant=tenant).first()
        if tenant
        else None
    )
    if not membership:
        return redirect("dashboard")

    try:
        membership_service.remove_member(membership, request.user)
    except membership_service.LastOwnerError:
        messages.error(
            request,
            "You're the only owner of this workspace, so you can't leave it. "
            "Make another member an owner first.",
        )
        return redirect("tenant_settings")

    request.session.pop("active_tenant_id", None)
    messages.success(request, f'You left "{tenant.name}".')
    return redirect("dashboard")


@login_required
@require_POST
def delete_workspace_view(request):
    """Delete the active workspace. Owners and superusers only, and only with
    the workspace's exact name typed back — the settings dialog asks for it,
    and it is checked again here so a stray or forged POST can't do it."""
    tenant = request.tenant
    if tenant is None:
        return redirect("dashboard")
    if not can_delete_workspace(request.user, tenant):
        raise PermissionDenied()
    if request.POST.get("confirm_name", "") != tenant.name:
        messages.error(
            request,
            "The name you typed doesn't match the workspace's, so nothing was deleted.",
        )
        return redirect(reverse("tenant_settings") + "#section-danger")

    name = tenant.name
    delete_workspace(tenant, request.user)
    request.session.pop("active_tenant_id", None)
    leave_support_view(request)
    messages.success(request, f'Workspace "{name}" was permanently deleted.')
    return redirect("dashboard")


class CreateWorkspaceForm(forms.Form):
    name = forms.CharField(max_length=255)
    owner_email = forms.EmailField(
        error_messages={"required": "Every workspace needs an owner."}
    )

    def clean_owner_email(self):
        email = self.cleaned_data["owner_email"].strip()
        owner = User.objects.filter(email__iexact=email, is_active=True).first()
        if owner is None:
            raise forms.ValidationError(
                "No active user with that email. If they haven't been approved yet, "
                "approve their access request into a new workspace instead."
            )
        return owner


class CreateTenantView(LoginRequiredMixin, FormView):
    """Superusers only: workspaces are gated, like the people who join them.

    A workspace is never without an owner, so the superuser names one: any
    active user, themselves included. For a company that hasn't signed up yet,
    approving its first person into a new workspace does the same job. A
    superuser who isn't the owner is taken in through the support view."""

    form_class = CreateWorkspaceForm
    template_name = "pages/create_tenant.html"

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and not request.user.is_superuser:
            raise PermissionDenied()
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        # Right after first-run setup the admin is setting up their own team.
        if not Membership.objects.filter(user=self.request.user).exists():
            return {"owner_email": self.request.user.email}
        return {}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_emails"] = (
            User.objects.filter(is_active=True)
            .exclude(email="")
            .order_by("email")
            .values_list("email", flat=True)
        )
        return context

    def form_valid(self, form):
        owner = form.cleaned_data["owner_email"]
        tenant = create_workspace(form.cleaned_data["name"].strip(), owner)
        if owner != self.request.user:
            publish(
                MemberJoined(
                    tenant_id=str(tenant.pk),
                    user_id=str(owner.pk),
                    role=Membership.Role.OWNER,
                    added_by_user_id=str(self.request.user.pk),
                )
            )
        if owner == self.request.user:
            leave_support_view(self.request)
            self.request.session["active_tenant_id"] = str(tenant.id)
        else:
            enter_support_view(self.request, tenant)
        messages.success(
            self.request, f'Workspace "{tenant.name}" created, owned by {owner.email}.'
        )
        return redirect("dashboard")


class TenantSettingsView(LoginRequiredMixin, TemplateView):
    template_name = "pages/tenant_settings.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        if tenant:
            members = list(
                Membership.objects.filter(tenant=tenant)
                .select_related("user")
                .order_by("created_at")
            )
            user = self.request.user
            can_manage = membership_service.can_manage_members(user, tenant)
            can_manage_owners = membership_service.can_manage_owners(user, tenant)
            owner_count = sum(m.role == Membership.Role.OWNER for m in members)
            for m in members:
                is_owner = m.role == Membership.Role.OWNER
                m.last_owner = is_owner and owner_count == 1
                # What this viewer may do to the row. The service checks again.
                m.role_choices = (
                    []
                    if not can_manage or m.last_owner or (is_owner and not can_manage_owners)
                    else [
                        (value, label)
                        for value, label in Membership.Role.choices
                        if value != Membership.Role.OWNER or can_manage_owners
                    ]
                )
                m.removable = (
                    m.user_id != user.pk
                    and can_manage
                    and not m.last_owner
                    and (not is_owner or can_manage_owners)
                )
            context["members"] = members
            own = next((m for m in members if m.user_id == user.pk), None)
            context["can_leave"] = own is not None and not own.last_owner
            context["is_last_owner"] = own is not None and own.last_owner
            context["can_delete_workspace"] = can_delete_workspace(
                self.request.user, tenant
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

            context["is_admin"] = is_workspace_admin(self.request)
            if context["is_admin"]:
                context["workspace_tokens"] = APIToken.objects.filter(
                    kind=APIToken.Kind.WORKSPACE, tenant=tenant
                ).select_related("created_by")
                context["new_token_value"] = self.request.session.pop("new_token_value", None)
                context["new_token_name"] = self.request.session.pop("new_token_name", None)
            # Drives the minimal "Install GitHub App" entry point (Phase 2).
            context["github_app_enabled"] = settings.GITHUB_APP_ENABLED
        return context


@login_required
@require_POST
def invite_member(request):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    if not is_workspace_admin(request):
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
    publish(
        MemberJoined(
            tenant_id=str(tenant.pk),
            user_id=str(invitee.pk),
            role=role,
            added_by_user_id=str(request.user.pk),
        )
    )
    messages.success(request, f"{email} added as {role}.")
    return redirect("tenant_settings")


@login_required
@require_POST
def remove_member(request, membership_id):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    target = get_object_or_404(Membership, id=membership_id, tenant=tenant)
    try:
        membership_service.remove_member(target, request.user)
    except membership_service.NotAllowed as e:
        messages.error(request, str(e))
    except membership_service.LastOwnerError as e:
        messages.error(request, str(e))
    else:
        messages.success(request, f"{target.user.email} removed.")
    return redirect(f"{reverse('tenant_settings')}#section-members")


@login_required
@require_POST
def change_member_role(request, membership_id):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    target = get_object_or_404(Membership, id=membership_id, tenant=tenant)
    try:
        membership_service.change_role(target, request.POST.get("role", ""), request.user)
    except (membership_service.NotAllowed, ValueError) as e:
        messages.error(request, str(e))
    else:
        messages.success(
            request, f"{target.user.email} is now {target.get_role_display().lower()}."
        )
    return redirect(f"{reverse('tenant_settings')}#section-members")


@login_required
@require_POST
def add_connection(request):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    if not is_workspace_admin(request):
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

    if not is_workspace_admin(request):
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
    """Return the decrypted access token for a real admin/owner member.

    The token is a secret and is deliberately never rendered into the settings
    page. The edit-token modal's "Show" control calls this endpoint so the
    token only crosses the wire on an explicit, authenticated, CSRF-protected
    request — never sitting in the page source.
    """
    from django.http import JsonResponse

    tenant = request.tenant
    if not tenant:
        return JsonResponse({"error": "No active workspace."}, status=400)

    # Deliberately not is_workspace_admin(): a superuser in the support view
    # never needs the partner's raw token, so the gate is a real membership.
    if not has_admin_membership(request):
        if getattr(request, "tenant_is_support_view", False):
            return JsonResponse(
                {"error": "Not available in support view."}, status=403
            )
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

    if not is_workspace_admin(request):
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
    if not is_workspace_admin(request):
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

    found = discover(provider_type, base_url, api_key)
    models = found.models
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
            f'Provider "{display_name}" added — {len(models)} models '
            f"this key can use.",
        )
    else:
        why = f" The provider said: {found.reason}." if found.reason else ""
        messages.warning(
            request,
            f'Provider "{display_name}" added, but no models this key can '
            f"use were found.{why} Add them manually via Edit.",
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
    if not is_workspace_admin(request):
        return HttpResponse('<span class="badge badge-error">Forbidden</span>')

    provider = get_object_or_404(LLMProvider, id=provider_id, tenant=tenant)
    found = discover(provider.provider_type, provider.base_url, provider.api_key)
    if found.models:
        provider.available_models = found.models
        provider.save(update_fields=["available_models"])
        return HttpResponse(
            f'<span class="badge badge-success">{len(found.models)} usable models — '
            f"reload to use</span>"
        )
    title = f' title="{escape(found.reason)}"' if found.reason else ""
    return HttpResponse(f'<span class="badge badge-warning"{title}>none found</span>')


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
