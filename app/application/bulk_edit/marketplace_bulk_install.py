from __future__ import annotations

from django.core.exceptions import ValidationError

from app.application import marketplace_service
from app.application.bulk_edit.bulk_edit_result import BulkEditResult
from app.application.errors import NotFoundError
from app.domain.models import MarketplaceStandard


class MarketplaceBulkInstall:
    """Installs or updates many Marketplace standards in a workspace at once,
    each as installing or updating one does (an update queues the new
    version to run on the projects it is attached to). One the workspace
    already has, or already has at the newest version, stays as it is."""

    ACTIONS = ("install", "update")

    def __init__(self, tenant, user):
        self.tenant = tenant
        self.user = user

    def standards(self, ids) -> list[MarketplaceStandard]:
        try:
            return list(MarketplaceStandard.objects.filter(pk__in=list(ids)))
        except (ValidationError, ValueError):
            raise NotFoundError("Unknown Marketplace standard.")

    def apply(self, action: str, ids, value: str = "") -> BulkEditResult:
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown action {action!r}.")
        return getattr(self, action)(self.standards(ids))

    def _result(self, done: str) -> BulkEditResult:
        return BulkEditResult(done=done, noun="standard", noun_plural="standards")

    def install(self, standards) -> BulkEditResult:
        result = self._result("Installed")
        for mp in standards:
            _, created = marketplace_service.install_standard(self.tenant, self.user, mp.slug)
            if created:
                result.changed += 1
            else:
                result.unchanged += 1
        return result

    def update(self, standards) -> BulkEditResult:
        result = self._result("Updated")
        copies = marketplace_service.installed_by_slug(self.tenant, standards)
        for mp in standards:
            installed = copies.get(mp.slug)
            if installed is None:
                result.skip("not installed")
            elif not marketplace_service.update_available(installed, mp):
                result.unchanged += 1
            else:
                marketplace_service.update_standard(self.tenant, self.user, mp.slug)
                result.changed += 1
        return result
