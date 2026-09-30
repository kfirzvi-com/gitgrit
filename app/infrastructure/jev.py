"""A thin client for Jev, TypeSafe's System One model.

Jev is not a chat model: it takes a JSON ``state`` plus a handful of typed
questions (yes/no, pick-one, score) and returns probabilities, all in one
round-trip. The architecture map uses it to judge link candidates the code
scanner finds (``app.domain.architecture.links``) — one call per candidate —
so this module hides the SDK behind three small types the rest of the app
can log, fake and replay:

* ``JevAnswer`` / ``JevResult`` — plain frozen dataclasses. The SDK's answer
  objects are pydantic models with type-specific fields (and ``ScoreAnswer``
  keys its probabilities by ``int``); flattening them here means callers and
  cassettes never see SDK classes, and every key is a string.
* ``JevClient`` — one ``ask`` per candidate, ``ask_many`` fanning out over a
  thread pool. A failed call is a ``JevError`` for that key only; the map run
  decides what to do with partial results.
* ``RecordingJevClient`` — writes every real answer to a JSON cassette keyed
  by a hash of the request, so the eval commands and the tests can replay a
  real run offline (``tests/jev_support.ReplayJevClient``).
* ``client_for(record=, replay=)`` — the one place the eval commands get
  their client from: a replay, the settings client, or that client recorded.

Retries live in the SDK (429/5xx with backoff); we pass its defaults and only
wrap what still fails. This module imports ``django.conf.settings`` and
nothing else from Django, so it can be used from management commands, the
worker, and pure tests alike.
"""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any, Callable, Iterable

from django.conf import settings
from typesafe_sdk import (
    ChoiceAnswer,
    NoulAnswer,
    RetryPolicy,
    ScoreAnswer,
    TypeSafeClient,
    TypeSafeError,
)


class JevError(RuntimeError):
    """A Jev call failed (API error, transport failure, or replay miss)."""

    def __init__(self, message: str, cause: BaseException | None = None):
        super().__init__(message)
        self.cause = cause


@dataclass(frozen=True)
class JevAnswer:
    kind: str  # "noul" | "choice" | "score"
    noul: float | None = None
    choice: str | None = None
    score: float | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)  # keys always str

    @classmethod
    def from_sdk(cls, answer: Any) -> "JevAnswer":
        if isinstance(answer, NoulAnswer):
            return cls(kind="noul", noul=answer.noul)
        if isinstance(answer, ChoiceAnswer):
            return cls(
                kind="choice",
                choice=answer.choice,
                confidence=answer.confidence,
                probabilities=dict(answer.probabilities),
            )
        if isinstance(answer, ScoreAnswer):
            return cls(
                kind="score",
                score=answer.score,
                confidence=answer.confidence,
                probabilities={str(k): v for k, v in answer.probabilities.items()},
            )
        raise JevError(f"unknown Jev answer type: {type(answer).__name__}")


@dataclass(frozen=True)
class JevResult:
    model: str  # versioned id Jev reported, e.g. "jev-1.13.0"
    answers: dict[str, JevAnswer]
    input_tokens: int
    latency_ms: int

    def to_log(self) -> dict:
        return {
            "model": self.model,
            "input_tokens": self.input_tokens,
            "latency_ms": self.latency_ms,
            "answers": {name: asdict(a) for name, a in self.answers.items()},
        }

    @classmethod
    def from_log(cls, data: dict) -> "JevResult":
        return cls(
            model=data["model"],
            answers={name: JevAnswer(**a) for name, a in data["answers"].items()},
            input_tokens=int(data["input_tokens"]),
            latency_ms=int(data["latency_ms"]),
        )


def jev_enabled() -> bool:
    """On only when switched on AND keyed; an air-gapped deploy never calls out."""
    return bool(settings.JEV_ENABLED and settings.TYPESAFE_API_KEY and not settings.AIRGAPPED)


def cassette_key(state: Any, questions: Any) -> str:
    """Deterministic id for one request, shared by recording and replay."""
    canonical = json.dumps(
        [state, _plain_questions(questions)],
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _plain_questions(questions: Any) -> Any:
    # SDK question objects are pydantic models; dict questions pass through.
    return {
        name: q.model_dump() if hasattr(q, "model_dump") else q
        for name, q in questions.items()
    }


def _new_usage() -> dict:
    return {"calls": 0, "input_tokens": 0, "failures": 0}


class JevClient:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        transport=None,
        retry: RetryPolicy | None = None,
    ):
        self.model = model
        self._client = TypeSafeClient(
            api_key=api_key,
            model=model,
            timeout=timeout,
            transport=transport,
            retry=retry if retry is not None else RetryPolicy(),
        )
        self.usage = _new_usage()
        self._lock = Lock()

    @classmethod
    def from_settings(cls) -> "JevClient | None":
        if not jev_enabled():
            return None
        return cls(
            api_key=settings.TYPESAFE_API_KEY,
            model=settings.JEV_MODEL,
            timeout=settings.JEV_TIMEOUT,
        )

    def ask(self, state, questions) -> JevResult:
        started = time.monotonic()
        with self._lock:
            self.usage["calls"] += 1
        try:
            response = self._client.system_one(state=state, questions=questions)
        except TypeSafeError as exc:
            with self._lock:
                self.usage["failures"] += 1
            raise JevError(f"jev call failed: {exc}", cause=exc) from exc
        result = JevResult(
            model=response.model,
            answers={name: JevAnswer.from_sdk(a) for name, a in response.answers.items()},
            input_tokens=response.usage.input_tokens or 0,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
        with self._lock:
            self.usage["input_tokens"] += result.input_tokens
        return result

    def ask_many(self, items: Iterable[tuple], *, workers: int = 8) -> dict:
        return _fan_out(self.ask, items, workers)


def _fan_out(ask: Callable, items: Iterable[tuple], workers: int) -> dict:
    """Run ``ask`` per (key, state, questions); one failure never sinks the batch."""
    items = list(items)
    if not items:
        return {}

    def one(item):
        key, state, questions = item
        try:
            return key, ask(state, questions)
        except JevError as exc:
            return key, exc
        except Exception as exc:  # a bug in one item must not lose the others
            return key, JevError(f"jev call failed: {exc}", cause=exc)

    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(items)))) as pool:
        return dict(pool.map(one, items))


class RecordingJevClient:
    """Wraps a client and saves every answer so the run can be replayed offline.

    The cassette is one JSON object ``{key: {"state", "questions", "result"}}``;
    an existing file is extended, so several eval runs can share one.
    """

    def __init__(self, inner, cassette_path):
        self.inner = inner
        self.path = Path(cassette_path)
        self._lock = Lock()
        self._entries = json.loads(self.path.read_text()) if self.path.exists() else {}

    @property
    def usage(self) -> dict:
        return self.inner.usage

    def ask(self, state, questions) -> JevResult:
        result = self.inner.ask(state, questions)
        entry = {
            "state": state,
            "questions": _plain_questions(questions),
            "result": result.to_log(),
        }
        with self._lock:
            self._entries[cassette_key(state, questions)] = entry
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self._entries, indent=1, sort_keys=True))
        return result

    def ask_many(self, items: Iterable[tuple], *, workers: int = 8) -> dict:
        return _fan_out(self.ask, items, workers)


class JevNotConfigured(JevError):
    """Jev is switched off, unkeyed or air-gapped, and no replay was given."""


class JevReplayMiss(JevError, KeyError):
    """The cassette has no entry for this (state, questions)."""


class ReplayJevClient:
    """Replays a ``RecordingJevClient`` cassette; unknown requests fail loudly
    so a changed prompt or state never silently passes on stale answers."""

    def __init__(self, cassette_path):
        self.path = Path(cassette_path)
        self._entries = json.loads(self.path.read_text())
        self.usage = _new_usage()

    def ask(self, state, questions) -> JevResult:
        self.usage["calls"] += 1
        key = cassette_key(state, questions)
        entry = self._entries.get(key)
        if entry is None:
            self.usage["failures"] += 1
            raise JevReplayMiss(f"no cassette entry {key[:12]}… in {self.path.name}")
        result = JevResult.from_log(entry["result"])
        self.usage["input_tokens"] += result.input_tokens
        return result

    def ask_many(self, items: Iterable[tuple], *, workers: int = 8) -> dict:
        return _fan_out(self.ask, items, workers)


def client_for(*, record: str | Path | None = None, replay: str | Path | None = None):
    """The Jev client an eval command runs with: ``ReplayJevClient(replay)``
    when a cassette is given (no key or network needed), otherwise the
    settings client, wrapped in a ``RecordingJevClient`` when ``record`` is
    set. ``record`` and ``replay`` are exclusive (``ValueError``); with
    neither, Jev being off is a ``JevNotConfigured``."""
    if record and replay:
        raise ValueError("record and replay are exclusive")
    if replay:
        return ReplayJevClient(replay)
    jev = JevClient.from_settings()
    if jev is None:
        raise JevNotConfigured(
            "Jev is not configured: set JEV_ENABLED=True and TYPESAFE_API_KEY (and AIRGAPPED off)"
        )
    if record:
        return RecordingJevClient(jev, record)
    return jev
