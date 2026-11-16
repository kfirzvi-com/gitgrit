from __future__ import annotations

from dataclasses import dataclass

from app.application import marketplace_service

# Between several values in one data-filter-/data-group- attribute.
SEPARATOR = "|"

INSTALLED = "installed"
UPDATE = "update"
AVAILABLE = "available"


@dataclass
class MarketplaceRow:
    """A Marketplace standard as the Marketplace table shows it: the packs it
    is in, and whether the workspace has it — installed, installed with a
    newer version out (``update``), or not yet (``available``)."""

    standard: object
    installed: object = None

    @classmethod
    def for_standards(cls, standards, tenant) -> list["MarketplaceRow"]:
        """A row per standard; the workspace's copies read at once.
        ``standards`` should prefetch ``packs``."""
        standards = list(standards)
        copies = marketplace_service.installed_by_slug(tenant)
        return [cls(standard=s, installed=copies.get(s.slug)) for s in standards]

    @property
    def packs(self) -> tuple:
        return tuple(sorted(self.standard.packs.all(), key=lambda p: p.name.lower()))

    @property
    def status(self) -> str:
        if self.installed is None:
            return AVAILABLE
        return UPDATE if marketplace_service.update_available(self.installed, self.standard) else INSTALLED

    @property
    def sort_status(self) -> int:
        """Not installed first, then those with an update, then the rest."""
        return (AVAILABLE, UPDATE, INSTALLED).index(self.status)

    @property
    def events(self) -> tuple[str, ...]:
        return tuple(str(e) for e in (self.standard.criteria or {}).get("events", []) or ())

    @property
    def pack_names(self) -> str:
        return SEPARATOR.join(self._clean(p.name) for p in self.packs)

    @property
    def label_names(self) -> str:
        return SEPARATOR.join(self._clean(str(label)) for label in self.standard.suggested_labels or ())

    @property
    def event_values(self) -> str:
        return SEPARATOR.join(self._clean(e).lower() for e in self.events)

    @property
    def author(self) -> str:
        return self._clean(self.standard.author)

    @staticmethod
    def _clean(text: str) -> str:
        return (text or "").replace(SEPARATOR, "/").strip()
