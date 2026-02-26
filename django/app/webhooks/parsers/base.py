from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.events import DomainEvent


class BaseWebhookParser(ABC):
    @abstractmethod
    def parse(self, headers: dict, payload: dict) -> DomainEvent:
        """Parse a webhook payload into a DomainEvent."""
        ...
