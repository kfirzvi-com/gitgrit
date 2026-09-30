"""Test doubles for ``app.infrastructure.jev.JevClient``.

Anything that takes a Jev client (link enrichment, the eval commands) should
be exercised without the network: ``FakeJevClient`` answers from a dict or a
function and remembers what it was asked; ``ReplayJevClient`` (re-exported from
``app.infrastructure.jev``) answers from a cassette a ``RecordingJevClient``
wrote against the real model, so a real run's judgments can be re-applied
deterministically.
"""
from __future__ import annotations

from typing import Callable, Iterable

from app.infrastructure.jev import (  # noqa: F401 — re-exported for tests
    JevAnswer,
    JevError,
    JevReplayMiss,
    JevResult,
    ReplayJevClient,
)


def _fan_out(ask, items: Iterable[tuple]) -> dict:
    out = {}
    for key, state, questions in items:
        try:
            out[key] = ask(state, questions)
        except JevError as exc:
            out[key] = exc
        except Exception as exc:
            out[key] = JevError(f"jev call failed: {exc}", cause=exc)
    return out


class FakeJevClient:
    """Answers come from ``answers``: a ``{name: JevAnswer}`` dict returned for
    every call, or a ``(state, questions) -> {name: JevAnswer}`` function.
    ``raise_on`` makes every ``ask`` raise that exception instead."""

    model = "fake-jev"

    def __init__(
        self,
        answers: Callable | dict[str, JevAnswer] | None = None,
        *,
        raise_on: Exception | None = None,
    ):
        self._answers = answers if answers is not None else {}
        self.raise_on = raise_on
        self.calls: list[tuple] = []  # (state, questions) in call order
        self.usage = {"calls": 0, "input_tokens": 0, "failures": 0}

    def ask(self, state, questions) -> JevResult:
        self.calls.append((state, questions))
        self.usage["calls"] += 1
        if self.raise_on is not None:
            self.usage["failures"] += 1
            raise self.raise_on
        answers = self._answers(state, questions) if callable(self._answers) else self._answers
        return JevResult(model=self.model, answers=dict(answers), input_tokens=0, latency_ms=0)

    def ask_many(self, items: Iterable[tuple], *, workers: int = 8) -> dict:
        return _fan_out(self.ask, items)



def link_answers(
    choice: str = "A",
    *,
    p: float = 0.95,
    confidence: float = 0.9,
    runtime: float = 0.95,
    inactive: float = 0.02,
    kind: str = "runtime",
    probabilities: dict[str, float] | None = None,
) -> dict[str, JevAnswer]:
    """The four answers the link stage asks for one candidate, as Jev returns
    them: ``choice`` for ``target`` with probability ``p`` (or the full
    ``probabilities`` map), the ``runtime_call`` and ``inactive`` nouls, and
    ``kind`` for ``edge_kind``. The defaults confirm option ``A`` at
    link ≈ 0.88."""
    probs = probabilities or {choice: p}
    return {
        "target": JevAnswer(kind="choice", choice=choice, confidence=confidence, probabilities=probs),
        "runtime_call": JevAnswer(kind="noul", noul=runtime),
        "inactive": JevAnswer(kind="noul", noul=inactive),
        "edge_kind": JevAnswer(kind="choice", choice=kind, confidence=0.9, probabilities={kind: 0.9}),
    }


def use_jev(monkeypatch, client):
    """Make ``JevClient.for_tenant()`` (the composition root's switch) and
    ``JevClient.from_settings()`` (the eval commands') hand back ``client`` — a
    fake, or ``None`` for "Jev off" — so no provider row, env var or setting is
    touched. Returns ``client``."""
    monkeypatch.setattr(
        "app.infrastructure.jev.JevClient.for_tenant", classmethod(lambda cls, tenant: client)
    )
    monkeypatch.setattr("app.infrastructure.jev.JevClient.from_settings", classmethod(lambda cls: client))
    return client
