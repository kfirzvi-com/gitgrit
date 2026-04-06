from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView

from app.domain.models import (
    MarketplacePack,
    MarketplacePolicy,
    Policy,
    PolicyLabel,
)


class MarketplaceBrowseView(LoginRequiredMixin, ListView):
    template_name = "pages/marketplace_browse.html"
    context_object_name = "policies"

    def get_queryset(self):
        return MarketplacePolicy.objects.all()

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["packs"] = MarketplacePack.objects.prefetch_related("policies").all()
        # Track which marketplace policies the tenant already installed
        tenant = self.request.tenant
        if tenant:
            ctx["installed_slugs"] = set(
                Policy.objects.filter(
                    tenant=tenant,
                    source_marketplace_policy__isnull=False,
                ).values_list("source_marketplace_policy__slug", flat=True)
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
            for p in Policy.objects.filter(
                tenant=tenant,
                source_marketplace_policy__in=self.object.policies.all(),
            ).select_related("source_marketplace_policy"):
                installed_map[p.source_marketplace_policy.slug] = p
        ctx["installed_map"] = installed_map
        return ctx


class MarketplacePolicyPreviewView(LoginRequiredMixin, DetailView):
    template_name = "pages/marketplace_policy_preview.html"
    model = MarketplacePolicy
    slug_url_kwarg = "slug"
    context_object_name = "mp_policy"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        tenant = self.request.tenant
        installed = None
        if tenant:
            installed = Policy.objects.filter(
                tenant=tenant,
                source_marketplace_policy=self.object,
            ).first()
        ctx["installed_policy"] = installed
        ctx["update_available"] = (
            installed
            and installed.source_version is not None
            and installed.source_version < self.object.version
        )
        return ctx


@login_required
@require_POST
def install_marketplace_policy(request, slug):
    mp = get_object_or_404(MarketplacePolicy, slug=slug)
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")

    # Check if already installed
    existing = Policy.objects.filter(
        tenant=tenant, source_marketplace_policy=mp
    ).first()
    if existing:
        messages.info(request, f'"{mp.name}" is already installed.')
        return redirect("policy_detail", pk=existing.pk)

    # Create/reuse labels
    labels = []
    for label_name in mp.suggested_labels:
        label, _ = PolicyLabel.objects.get_or_create(
            tenant=tenant, name=label_name
        )
        labels.append(label)

    # Create tenant policy
    policy = Policy.objects.create(
        tenant=tenant,
        name=mp.name,
        description=mp.description,
        code=mp.code,
        criteria=mp.criteria,
        test_cases=mp.test_cases,
        source_marketplace_policy=mp,
        source_version=mp.version,
        enabled=True,
        draft=False,
    )
    policy.labels.set(labels)

    messages.success(request, f'Installed "{mp.name}" — you can customize it now.')
    return redirect("policy_detail", pk=policy.pk)


@login_required
@require_POST
def update_marketplace_policy(request, slug):
    mp = get_object_or_404(MarketplacePolicy, slug=slug)
    tenant = request.tenant
    if not tenant:
        messages.error(request, "No active workspace.")
        return redirect("marketplace_browse")

    policy = get_object_or_404(
        Policy, tenant=tenant, source_marketplace_policy=mp
    )

    policy.code = mp.code
    policy.description = mp.description
    policy.criteria = mp.criteria
    policy.test_cases = mp.test_cases
    policy.source_version = mp.version
    policy.save()

    # Add any new suggested labels
    for label_name in mp.suggested_labels:
        label, _ = PolicyLabel.objects.get_or_create(
            tenant=tenant, name=label_name
        )
        policy.labels.add(label)

    messages.success(
        request, f'Updated "{policy.name}" to v{mp.version}.'
    )
    return redirect("policy_detail", pk=policy.pk)


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

    for mp in pack.policies.all():
        existing = Policy.objects.filter(
            tenant=tenant, source_marketplace_policy=mp
        ).first()
        if existing:
            skipped_count += 1
            continue

        labels = []
        for label_name in mp.suggested_labels:
            label, _ = PolicyLabel.objects.get_or_create(
                tenant=tenant, name=label_name
            )
            labels.append(label)

        policy = Policy.objects.create(
            tenant=tenant,
            name=mp.name,
            description=mp.description,
            code=mp.code,
            criteria=mp.criteria,
            test_cases=mp.test_cases,
            source_marketplace_policy=mp,
            source_version=mp.version,
            enabled=True,
            draft=False,
        )
        policy.labels.set(labels)
        installed_count += 1

    parts = []
    if installed_count:
        parts.append(f"{installed_count} installed")
    if skipped_count:
        parts.append(f"{skipped_count} already existed")
    messages.success(request, f'Pack "{pack.name}": {", ".join(parts)}.')
    return redirect("marketplace_pack_detail", slug=pack.slug)
