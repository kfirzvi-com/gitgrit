from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from app.domain.models import (
    MarketplacePack,
    MarketplaceStandard,
    Standard,
    StandardLabel,
)
from app.application.standard_service import create_standard_version


class MarketplaceBrowseView(LoginRequiredMixin, ListView):
    template_name = "pages/marketplace_browse.html"
    context_object_name = "standards"

    def get_queryset(self):
        return MarketplaceStandard.objects.all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["packs"] = MarketplacePack.objects.prefetch_related("standards").all()
        # Track which marketplace standards the tenant already installed
        tenant = self.request.tenant
        if tenant:
            ctx["installed_slugs"] = set(
                Standard.objects.filter(
                    tenant=tenant,
                    source_marketplace_standard__isnull=False,
                ).values_list("source_marketplace_standard__slug", flat=True)
            )
        else:
            ctx["installed_slugs"] = set()
        return ctx


class MarketplacePackDetailView(LoginRequiredMixin, DetailView):
    template_name = "pages/marketplace_pack_detail.html"
    model = MarketplacePack
    slug_url_kwarg = "slug"
    context_object_name = "pack"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        installed_map = {}
        if tenant:
            for p in Standard.objects.filter(
                tenant=tenant,
                source_marketplace_standard__in=self.object.standards.all(),
            ).select_related("source_marketplace_standard"):
                installed_map[p.source_marketplace_standard.slug] = p
        ctx["installed_map"] = installed_map
        return ctx


class MarketplaceStandardPreviewView(LoginRequiredMixin, DetailView):
    template_name = "pages/marketplace_standard_preview.html"
    model = MarketplaceStandard
    slug_url_kwarg = "slug"
    context_object_name = "mp_standard"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        installed = None
        if tenant:
            installed = Standard.objects.filter(
                tenant=tenant,
                source_marketplace_standard=self.object,
            ).first()
        ctx["installed_standard"] = installed
        ctx["update_available"] = (
            installed
            and installed.source_version is not None
            and installed.source_version < self.object.version
        )
        return ctx


@login_required
@require_POST
def install_marketplace_standard(request, slug):
    mp = get_object_or_404(MarketplaceStandard, slug=slug)
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")

    # Check if already installed
    existing = Standard.objects.filter(
        tenant=tenant, source_marketplace_standard=mp
    ).first()
    if existing:
        messages.info(request, f'"{mp.name}" is already installed.')
        return redirect("standard_detail", pk=existing.pk)

    # Create/reuse labels
    labels = []
    for label_name in mp.suggested_labels:
        label, _ = StandardLabel.objects.get_or_create(
            tenant=tenant, name=label_name
        )
        labels.append(label)

    # Create tenant standard
    standard = Standard.objects.create(
        tenant=tenant,
        name=mp.name,
        description=mp.description,
        code=mp.code,
        criteria=mp.criteria,
        test_cases=mp.test_cases,
        source_marketplace_standard=mp,
        source_version=mp.version,
        enabled=True,
        draft=False,
    )
    standard.labels.set(labels)
    create_standard_version(standard, request.user, f"Installed from marketplace: {mp.name} v{mp.version}")

    messages.success(request, f'Installed "{mp.name}" — you can customize it now.')
    return redirect("standard_detail", pk=standard.pk)


@login_required
@require_POST
def update_marketplace_standard(request, slug):
    mp = get_object_or_404(MarketplaceStandard, slug=slug)
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")

    standard = get_object_or_404(
        Standard, tenant=tenant, source_marketplace_standard=mp
    )

    standard.code = mp.code
    standard.description = mp.description
    standard.criteria = mp.criteria
    standard.test_cases = mp.test_cases
    standard.source_version = mp.version
    standard.save()

    # Add any new suggested labels
    for label_name in mp.suggested_labels:
        label, _ = StandardLabel.objects.get_or_create(
            tenant=tenant, name=label_name
        )
        standard.labels.add(label)

    create_standard_version(standard, request.user, f"Updated from marketplace: {mp.name} v{mp.version}")

    messages.success(
        request, f'Updated "{standard.name}" to v{mp.version}.'
    )
    return redirect("standard_detail", pk=standard.pk)


@login_required
@require_POST
def install_marketplace_pack(request, slug):
    pack = get_object_or_404(MarketplacePack, slug=slug)
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")

    installed_count = 0
    skipped_count = 0

    for mp in pack.standards.all():
        existing = Standard.objects.filter(
            tenant=tenant, source_marketplace_standard=mp
        ).first()
        if existing:
            skipped_count += 1
            continue

        labels = []
        for label_name in mp.suggested_labels:
            label, _ = StandardLabel.objects.get_or_create(
                tenant=tenant, name=label_name
            )
            labels.append(label)

        standard = Standard.objects.create(
            tenant=tenant,
            name=mp.name,
            description=mp.description,
            code=mp.code,
            criteria=mp.criteria,
            test_cases=mp.test_cases,
            source_marketplace_standard=mp,
            source_version=mp.version,
            enabled=True,
            draft=False,
        )
        standard.labels.set(labels)
        create_standard_version(standard, request.user, f"Installed from marketplace: {mp.name} v{mp.version}")
        installed_count += 1

    parts = []
    if installed_count:
        parts.append(f"{installed_count} installed")
    if skipped_count:
        parts.append(f"{skipped_count} already existed")
    messages.success(request, f'Pack "{pack.name}": {", ".join(parts)}.')
    return redirect("marketplace_pack_detail", slug=pack.slug)
