from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST

from app.domain.models import APIToken, Membership


@login_required
@require_POST
def create_api_token(request):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    name = request.POST.get("token_name", "").strip()
    if not name:
        messages.error(request, "Token name is required.")
        return redirect("tenant_settings")

    token_instance, raw_token = APIToken.generate()
    token_instance.user = request.user
    token_instance.tenant = tenant
    token_instance.name = name
    token_instance.save()

    # Store the raw token in the session once so it can be displayed
    request.session["new_token_value"] = raw_token
    request.session["new_token_name"] = name
    return redirect("tenant_settings")


@login_required
@require_POST
def revoke_api_token(request, token_id):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("tenant_settings")

    token = get_object_or_404(APIToken, id=token_id, tenant=tenant)

    # Only the token owner or a workspace admin can revoke
    membership = Membership.objects.filter(user=request.user, tenant=tenant).first()
    is_admin = membership and membership.role in (Membership.Role.OWNER, Membership.Role.ADMIN)
    if token.user != request.user and not is_admin:
        messages.error(request, "Permission denied.")
        return redirect("tenant_settings")

    token.delete()
    if request.headers.get("HX-Request"):
        return HttpResponse("")
    messages.success(request, f'Token "{token.name}" revoked.')
    return redirect("tenant_settings")
