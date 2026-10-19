from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from app.application import marketplace_service
from app.application.errors import NotFoundError
from app.domain.models import MarketplacePack, MarketplaceStandard


class MarketplaceBrowseView(LoginRequiredMixin, ListView):
    template_name = "pages/marketplace_browse.html"
    context_object_name = "standards"

    def get_queryset(self):
        return MarketplaceStandard.objects.all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["packs"] = MarketplacePack.objects.prefetch_related("standards").all()
        ctx["installed_slugs"] = set(marketplace_service.installed_by_slug(self.request.tenant))
        return ctx


class MarketplacePackDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/marketplace_pack_detail.html"
    model = MarketplacePack
    slug_url_kwarg = "slug"
    context_object_name = "pack"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["installed_map"] = marketplace_service.installed_by_slug(
            self.request.tenant, self.object.standards.all()
        )
        return ctx


class MarketplaceStandardPreviewView(LoginRequiredMixin, DetailView):
    template_name = "pages/marketplace_standard_preview.html"
    model = MarketplaceStandard
    slug_url_kwarg = "slug"
    context_object_name = "mp_standard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        installed = marketplace_service.installed_by_slug(
            self.request.tenant, [self.object]
        ).get(self.object.slug)
        ctx["installed_standard"] = installed
        ctx["update_available"] = marketplace_service.update_available(installed, self.object)
        return ctx


@login_required
@require_POST
def install_marketplace_standard(request, slug):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")
    try:
        standard, created = marketplace_service.install_standard(tenant, request.user, slug)
    except NotFoundError:
        raise Http404
    if created:
        messages.success(request, f'Installed "{standard.name}" — you can customize it now.')
    else:
        messages.info(request, f'"{standard.name}" is already installed.')
    return redirect("standard_detail", pk=standard.pk)


@login_required
@require_POST
def update_marketplace_standard(request, slug):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")
    try:
        standard, runs = marketplace_service.update_standard(tenant, request.user, slug)
    except NotFoundError:
        raise Http404
    messages.success(request, f'Updated "{standard.name}" to v{standard.source_version}.')
    # The new version is queued to run on every project the standard is
    # attached to — say so, like every other save path does.
    if runs:
        messages.info(request, runs["message"])
    return redirect("standard_detail", pk=standard.pk)


@login_required
@require_POST
def install_marketplace_pack(request, slug):
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")
    try:
        result = marketplace_service.install_pack(tenant, request.user, slug)
    except NotFoundError:
        raise Http404

    parts = []
    if result["installed"]:
        parts.append(f"{len(result['installed'])} installed")
    if result["skipped"]:
        parts.append(f"{len(result['skipped'])} already existed")
    messages.success(request, f'Pack "{result["pack"].name}": {", ".join(parts)}.')
    return redirect("marketplace_pack_detail", slug=result["pack"].slug)
