"""The Standard Marketplace: global, ready-made standards a workspace copies in.

Marketplace standards and packs are shared by every workspace (seeded from
``app/fixtures/marketplace``). Installing one copies it into the workspace as
an ordinary, editable ``Standard`` that remembers where it came from and at
which version, so a newer marketplace version can be offered as an update.
The web views and the public API both go through here.
"""
from app.application.errors import NotFoundError
from app.application.standard_service import create_standard_version
from app.domain.models import (
    MarketplacePack,
    MarketplaceStandard,
    Standard,
    StandardLabel,
    Tenant,
    User,
)


def get_marketplace_standard(slug: str) -> MarketplaceStandard:
    try:
        return MarketplaceStandard.objects.get(slug=slug)
    except MarketplaceStandard.DoesNotExist:
        raise NotFoundError(f"No marketplace standard {slug!r}.")


def get_pack(slug: str) -> MarketplacePack:
    try:
        return MarketplacePack.objects.prefetch_related("standards").get(slug=slug)
    except MarketplacePack.DoesNotExist:
        raise NotFoundError(f"No marketplace pack {slug!r}.")


def installed_by_slug(tenant: Tenant | None, standards=None) -> dict[str, Standard]:
    """The workspace's copies of marketplace standards, keyed by marketplace
    slug — optionally only those of ``standards``."""
    if tenant is None:
        return {}
    qs = Standard.objects.filter(
        tenant=tenant, source_marketplace_standard__isnull=False
    ).select_related("source_marketplace_standard")
    if standards is not None:
        qs = qs.filter(source_marketplace_standard__in=standards)
    return {s.source_marketplace_standard.slug: s for s in qs}


def update_available(installed: Standard | None, mp: MarketplaceStandard) -> bool:
    return bool(
        installed
        and installed.source_version is not None
        and installed.source_version < mp.version
    )


def install_standard(tenant: Tenant, user: User | None, slug: str) -> tuple[Standard, bool]:
    """Copy a marketplace standard into the workspace, enabled.

    Returns the workspace's standard and whether it was created; installing
    one the workspace already has is a no-op that returns the existing copy.
    """
    return _install(tenant, user, get_marketplace_standard(slug))


def install_pack(tenant: Tenant, user: User | None, slug: str) -> dict:
    """Install every standard in a pack the workspace doesn't have yet.

    Returns ``{"pack", "installed", "skipped"}``, the last two being lists of
    workspace standards: newly created, and already there.
    """
    pack = get_pack(slug)
    installed, skipped = [], []
    for mp in pack.standards.all():
        standard, created = _install(tenant, user, mp)
        (installed if created else skipped).append(standard)
    return {"pack": pack, "installed": installed, "skipped": skipped}


def update_standard(tenant: Tenant, user: User | None, slug: str) -> tuple[Standard, dict | None]:
    """Bring the workspace's copy up to the marketplace's latest version.

    Returns the standard and the summary of the runs the new version queued
    on attached projects (None when nothing was queued).
    """
    mp = get_marketplace_standard(slug)
    standard = Standard.objects.filter(tenant=tenant, source_marketplace_standard=mp).first()
    if standard is None:
        raise NotFoundError(f"{mp.name!r} isn't installed in this workspace.")
    standard.code = mp.code
    standard.description = mp.description
    standard.criteria = mp.criteria
    standard.test_cases = mp.test_cases
    standard.source_version = mp.version
    standard.save()
    standard.labels.add(*_labels(tenant, mp))
    runs = create_standard_version(
        standard, user, f"Updated from marketplace: {mp.name} v{mp.version}"
    )
    return standard, runs


def _install(tenant: Tenant, user: User | None, mp: MarketplaceStandard) -> tuple[Standard, bool]:
    existing = Standard.objects.filter(tenant=tenant, source_marketplace_standard=mp).first()
    if existing:
        return existing, False
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
    standard.labels.set(_labels(tenant, mp))
    create_standard_version(
        standard, user, f"Installed from marketplace: {mp.name} v{mp.version}"
    )
    return standard, True


def _labels(tenant: Tenant, mp: MarketplaceStandard) -> list[StandardLabel]:
    return [
        StandardLabel.objects.get_or_create(tenant=tenant, name=name)[0]
        for name in mp.suggested_labels
    ]
