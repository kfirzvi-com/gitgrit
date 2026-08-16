from __future__ import annotations

from abc import ABC, abstractmethod


class StandardRunner(ABC):
    @abstractmethod
    def run(self, standard_code: str, input_config: dict) -> dict:
        """Execute a standard script and return the result dict."""
        ...
