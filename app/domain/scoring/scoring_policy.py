from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.scoring.score import Score


class ScoringPolicy(ABC):
    """How a complete commit's results become its score."""

    @abstractmethod
    def score(self, results) -> Score: ...
