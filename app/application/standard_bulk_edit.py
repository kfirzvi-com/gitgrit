from __future__ import annotations

from django.core.exceptions import ValidationError

from app.application.bulk_edit_result import BulkEditResult
from app.application.errors import NotFoundError
from app.application.standard_service import StandardService
from app.domain.models import DraftCannotBeEnabled, Standard, StandardLabel


class StandardBulkEdit:
    """Changes many of a workspace's standards at once. Enabling one queues
    it to run on its projects, as enabling one by hand does; a draft can't be
    enabled and is skipped. Deleting archives (its versions and results
    stay)."""

    ACTIONS = ("enable", "disable", "add_label", "remove_label", "delete")

    def __init__(self, tenant, user):
        self.tenant = tenant
        self.user = user
        self.service = StandardService()

    def standards(self, ids) -> list[Standard]:
        try:
            return list(Standard.objects.filter(tenant=self.tenant, pk__in=list(ids)).prefetch_related("labels"))
        except (ValidationError, ValueError):
            raise NotFoundError("Unknown standard.")

    def apply(self, action: str, ids, value: str = "") -> BulkEditResult:
        if action not in self.ACTIONS:
            raise ValueError(f"Unknown action {action!r}.")
        return getattr(self, action)(self.standards(ids), value)

    def _result(self, done: str) -> BulkEditResult:
        return BulkEditResult(done=done, noun="standard", noun_plural="standards")

    def enable(self, standards, _value="") -> BulkEditResult:
        return self._set_enabled(standards, True)

    def disable(self, standards, _value="") -> BulkEditResult:
        return self._set_enabled(standards, False)

    def _set_enabled(self, standards, enabled: bool) -> BulkEditResult:
        result = self._result("Enabled" if enabled else "Disabled")
        for standard in standards:
            if standard.enabled == enabled:
                result.unchanged += 1
                continue
            try:
                self.service.set_enabled(self.tenant, self.user, standard.pk, enabled)
            except DraftCannotBeEnabled:
                result.skip("drafts can't be enabled")
                continue
            result.changed += 1
        return result

    def add_label(self, standards, name: str) -> BulkEditResult:
        name = (name or "").strip()
        if not name:
            raise ValueError("Name the label to add.")
        label = self._label(name) or StandardLabel.objects.create(tenant=self.tenant, name=name)
        result = self._result(f'Labelled "{label.name}":')
        for standard in standards:
            if label in standard.labels.all():
                result.unchanged += 1
            else:
                standard.labels.add(label)
                result.changed += 1
        return result

    def remove_label(self, standards, name: str) -> BulkEditResult:
        label = self._label((name or "").strip())
        if label is None:
            raise ValueError("No such label.")
        result = self._result(f'Removed "{label.name}" from')
        for standard in standards:
            if label in standard.labels.all():
                standard.labels.remove(label)
                result.changed += 1
            else:
                result.unchanged += 1
        return result

    def delete(self, standards, _value="") -> BulkEditResult:
        result = self._result("Deleted")
        for standard in standards:
            self.service.delete_standard(self.tenant, standard.pk)
            result.changed += 1
        return result

    def _label(self, name: str):
        """The workspace's label called ``name``, whatever its case."""
        return StandardLabel.objects.filter(tenant=self.tenant, name__iexact=name).first() if name else None
