from __future__ import annotations

from abc import ABC, abstractmethod


class PolicyRunner(ABC):
    @abstractmethod
    def run(self, policy_code: str, input_config: dict) -> dict:
        """Execute a policy script and return the result dict."""
        ...
