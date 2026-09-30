"""The Jev link stage: code-found link candidates judged by Jev, added to the
map when confirmed.

The LLM inference reads manifests and READMEs and misses the wiring that
lives in config files, compose files and SDK clients. ``links.py`` finds those
places deterministically; this module asks Jev four typed questions about
each one (which roster component it points to, is it a runtime call, is it
inactive text, what kind of edge) and turns the probabilities into a
``Decision`` with plain arithmetic the eval can tune:

    link = p(target) × runtime_call × (1 − inactive)

Bands: ``confirmed`` (≥ confirm) adds the edge, ``unsure`` is logged for the
escalation stage, ``dropped`` is logged, ``failed`` means Jev did not answer.
``Decision.link`` is always the score of the edge that would be added: when
Jev picks ``none``, or ``external`` and the code gave no name to draw, there is
no such edge and ``link`` is 0. ``test`` and ``dev_only`` edges are never drawn
even when confirmed (the map shows production topology).

Jev is strictly additive and never fails a map refresh: any exception from
the scanner or the client is caught and logged, and the inner topology is
returned unchanged. The same happens when more than 20 % of the asked
candidates failed (a partial run would bias the map toward whatever
happened to answer) and when the inner inference read no files (the
evidence gate must still reject that run).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Iterable

from django.conf import settings
from typesafe_sdk import Choice, Noul

from app.application.architecture.ports import (
    InferenceContext,
    RepositorySnapshot,
    TopologyInference,
)
from app.domain.architecture.links import DEFAULT_LIMIT, LinkCandidate, already_covered, find_link_candidates
from app.domain.architecture.naming import canonical_key
from app.domain.architecture.resolve import with_siblings
from app.domain.architecture.topology import (
    OUTBOUND,
    ComponentDecl,
    ExternalLink,
    InternalDependency,
    RepositoryTopology,
)
from app.infrastructure.jev import JevResult


@dataclass(frozen=True)
class Thresholds:
    """Cut-offs on the link score. Tuned 2026-09-30 on 53 labelled candidates
    (``tests/fixtures/jev/link_candidates.jsonl``): precision stayed 1.00 from
    0.50 up while recall fell from 0.74 to 0.36 at 0.80, and every bucket at or
    above 0.4 was right, so 0.60 keeps a margin under the curve."""

    confirm: float = 0.60
    unsure: float = 0.25
    min_target_confidence: float = 0.50


BANDS = ("confirmed", "unsure", "dropped", "failed")
EDGE_KINDS = ("runtime", "build", "test", "dev_only", "optional")
NEVER_DRAWN = frozenset({"test", "dev_only"})

EXTERNAL = "external"
NONE = "none"
MAX_FAILURE_SHARE = 0.20
DEFAULT_MAX_CANDIDATES = DEFAULT_LIMIT


# --- State and questions ------------------------------------------------------------


def component_for(candidate: LinkCandidate, components: Iterable[ComponentDecl] = ()) -> ComponentDecl:
    """The ``source_component`` Jev is shown: the declared component at
    ``candidate.source_path``, else a stand-in named after the last path
    segment (``"root"`` for the repository root) of kind ``other``. The eval
    command has no topology and always gets the stand-in; cassette keys hash
    the state, so the stand-in must be the same in both paths."""
    for component in components:
        if component.path == candidate.source_path:
            return component
    path = candidate.source_path
    return ComponentDecl(path=path, name=path.rsplit("/", 1)[-1] if path else "root", kind="other")


def build_state(candidate: LinkCandidate, component: ComponentDecl) -> dict:
    """The JSON Jev judges: the source component, where the reference was
    found, the snippet, and the roster shortlist keyed by option id."""
    return {
        "source_component": {"name": component.name, "path": component.path, "kind": component.kind},
        "file": candidate.file,
        "reference": candidate.reference,
        "reference_kind": candidate.reference_kind,
        "code": candidate.code,
        "candidates": {o.id: {"ref": o.ref, "name": o.name, "kind": o.kind} for o in candidate.options},
    }


def target_criteria(candidate: LinkCandidate) -> dict[str, str]:
    """Option ids (with a one-line description each) + ``external`` + ``none``."""
    criteria = {o.id: f"{o.name} ({o.ref})" for o in candidate.options}
    criteria[EXTERNAL] = (
        "a third-party service run by another company, referenced directly or through its "
        "client SDK or package (for example Stripe, Auth0, SendGrid, Twilio)"
    )
    criteria[NONE] = (
        "not a service run by another party: a general-purpose library or framework, a local "
        "file, a database, cache or message broker the component itself operates, a build tool "
        "or package registry, a placeholder, or the component itself"
    )
    return criteria


def build_questions(candidate: LinkCandidate) -> dict:
    # Jev is literal: every form a reference can take is spelled out, and the
    # two catch-all answers say exactly what falls into them.
    forms = (
        "`reference` may be a service name, a hostname or URL, an environment variable that "
        "holds a service address, a docker-compose service or container image, a queue or "
        "topic name (pick the service that owns or produces it), or a client SDK or package "
        "for a service. "
    )
    if candidate.options:
        target = (
            "Which of `candidates` is the workspace service that `reference` in `code` refers "
            "to? " + forms +
            "Pick `external` if it refers to a third-party service run by another company, "
            "including through that company's SDK or package. Pick `none` if it is not a "
            "service run by another party: a general-purpose library or framework, a local "
            "file, a database, cache or broker the component itself operates, a build tool or "
            "package registry, or a placeholder."
        )
    else:
        target = (
            "`candidates` is empty: no workspace service matched `reference`. " + forms +
            "Pick `external` if `reference` in `code` refers to a third-party service run by "
            "another company, including through that company's SDK or package. Pick `none` "
            "if it is not a service run by another party: a general-purpose library or "
            "framework, a local file, a database, cache or broker the component itself "
            "operates, a build tool or package registry, or a placeholder."
        )
    return {
        "target": Choice(instructions=target, criteria=target_criteria(candidate)),
        "runtime_call": Noul(
            instructions=(
                "Does `code` indicate that `source_component`, while it is running, connects "
                "to, calls, publishes to or consumes from the service behind `reference`? "
                "Configuration counts as evidence when the running component uses it: a "
                "service URL or hostname in a config or environment file, a docker-compose "
                "`depends_on` or service image, a queue or topic it publishes to or consumes "
                "from, a client SDK it installs or imports. Answer no when `reference` is "
                "used only at build or deploy time, only in tests, only in documentation or "
                "comments, or is commented out."
            )
        ),
        "inactive": Noul(
            instructions=(
                "Is `reference` in `code` present only in a comment, commented-out code, an "
                "example, documentation text, or a test fixture or mock?"
            )
        ),
        "edge_kind": Choice(
            instructions="How is the service behind `reference` used by `source_component`?",
            criteria={
                "runtime": "needed to serve requests or run jobs",
                "build": "only at build or deploy time",
                "test": "only in tests",
                "dev_only": "a local development stand-in",
                "optional": "feature-flagged or best-effort",
            },
        ),
    }


# --- Decision ------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    candidate: LinkCandidate
    band: str
    link: float
    target_ref: str | None
    external_name: str
    edge_kind: str | None
    drawn: bool
    result: JevResult | None
    error: str = ""
    choice: str | None = None  # Jev's raw ``target`` choice (option id, "external" or "none")

    def to_log(self) -> dict:
        c = self.candidate
        return {
            "source_path": c.source_path,
            "file": c.file,
            "line": c.line,
            "reference": c.reference,
            "reference_kind": c.reference_kind,
            "options": [o.ref for o in c.options],
            "external_hint": c.external_name,
            "choice": self.choice,
            "band": self.band,
            "link": round(self.link, 4),
            "target_ref": self.target_ref,
            "external_name": self.external_name,
            "edge_kind": self.edge_kind,
            "drawn": self.drawn,
            "error": self.error,
            "jev": self.result.to_log() if self.result is not None else None,
        }


def failed_decision(candidate: LinkCandidate, error: str, result: JevResult | None = None) -> Decision:
    return Decision(
        candidate=candidate, band="failed", link=0.0, target_ref=None, external_name="",
        edge_kind=None, drawn=False, result=result, error=error,
    )


def decide(candidate: LinkCandidate, result: JevResult, thresholds: Thresholds = Thresholds()) -> Decision:
    """Plan §2c: turn Jev's answers into a band and, when confirmed, an edge."""
    answers = result.answers
    missing = [name for name in ("target", "runtime_call", "inactive", "edge_kind") if name not in answers]
    if missing:
        return failed_decision(candidate, f"missing answers: {', '.join(missing)}", result)

    target = answers["target"]
    choice = target.choice
    kind = answers["edge_kind"].choice
    edge_kind = kind if kind in EDGE_KINDS else None

    if choice == NONE or (choice == EXTERNAL and not candidate.external_name):
        # Nothing would be added ("not a service", or "outside" with no name to
        # draw), so the score of that edge is 0 whatever the probabilities.
        return Decision(
            candidate=candidate, band="dropped", link=0.0, target_ref=None, external_name="",
            edge_kind=edge_kind, drawn=False, result=result, choice=choice,
        )

    p_target = target.probabilities.get(choice or "", target.confidence or 0.0) or 0.0
    runtime_call = answers["runtime_call"].noul or 0.0
    inactive = answers["inactive"].noul or 0.0
    link = max(0.0, min(1.0, p_target * runtime_call * (1 - inactive)))

    target_ref: str | None = None
    external_name = ""
    if choice == EXTERNAL:
        external_name = candidate.external_name
    else:
        options = {o.id: o for o in candidate.options}
        if choice not in options:
            return failed_decision(candidate, f"unknown target choice {choice!r}", result)
        target_ref = options[choice].ref

    if link >= thresholds.confirm:
        band = "confirmed"
    elif link >= thresholds.unsure:
        band = "unsure"
    else:
        band = "dropped"
    if (
        band == "confirmed"
        and target_ref is not None
        and len(candidate.options) >= 2
        and (target.confidence or 0.0) < thresholds.min_target_confidence
    ):
        band = "unsure"  # two roster options and Jev could not tell them apart
    if band != "confirmed":
        target_ref, external_name = None, ""

    return Decision(
        candidate=candidate,
        band=band,
        link=link,
        target_ref=target_ref,
        external_name=external_name,
        edge_kind=edge_kind,
        drawn=band == "confirmed" and edge_kind not in NEVER_DRAWN,
        result=result,
        choice=choice,
    )


def decide_all(
    candidates: Iterable[LinkCandidate], results: dict, thresholds: Thresholds = Thresholds()
) -> list[Decision]:
    """One ``Decision`` per candidate from an ``ask_many`` result map keyed by
    position: a ``JevResult`` is decided, anything else (a ``JevError``, or no
    entry at all) is a failure carrying the error text."""
    decisions = []
    for i, candidate in enumerate(candidates):
        result = results.get(i)
        if isinstance(result, JevResult):
            decisions.append(decide(candidate, result, thresholds))
        else:
            error = "no answer" if result is None else (str(result) or "no answer")
            decisions.append(failed_decision(candidate, error))
    return decisions


# --- Enrichment ------------------------------------------------------------------------


def enrich_with_links(
    topology: RepositoryTopology,
    snapshot: RepositorySnapshot,
    context: InferenceContext,
    jev,
    *,
    thresholds: Thresholds = Thresholds(),
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
    workers: int = 8,
) -> tuple[RepositoryTopology, list[Decision]]:
    """Add Jev-confirmed links to ``topology``. Never raises: on any failure
    the inner topology comes back unchanged with whatever was decided."""
    decisions: list[Decision] = []
    try:
        return _enrich(topology, snapshot, context, jev, thresholds, max_candidates, workers, decisions)
    except Exception as exc:  # Jev never fails a map refresh
        context.log(f"jev-links skipped: {type(exc).__name__}: {exc}")
        return topology, decisions


def _enrich(topology, snapshot, context, jev, thresholds, max_candidates, workers, decisions) -> tuple:
    if not topology.evidence.files_read:
        context.log("jev-links skipped: the inference read no files")
        return topology, decisions

    roster = with_siblings(context.roster, context.full_path, topology.components)
    scan = find_link_candidates(
        snapshot.list_files(), snapshot.read_file, topology.components, roster,
        this_repo=context.full_path, limit=max_candidates,
    )
    candidates = [c for c in scan.candidates if not already_covered(c, topology)]
    context.log(
        f"jev-links: {len(scan.candidates)} candidates from {len(scan.files_read)} files, "
        f"{len(candidates)} not already on the map"
    )
    if not candidates:
        return topology, decisions

    items = [
        (i, build_state(c, component_for(c, topology.components)), build_questions(c))
        for i, c in enumerate(candidates)
    ]
    results = jev.ask_many(items, workers=workers)
    decisions.extend(decide_all(candidates, results, thresholds))
    for decision in decisions:
        context.log("jev-link " + json.dumps(decision.to_log(), ensure_ascii=False, default=str))

    failed = sum(1 for d in decisions if d.band == "failed")
    if failed / len(candidates) > MAX_FAILURE_SHARE:
        context.log(f"jev-links disabled for this run: {failed}/{len(candidates)} failed")
        return topology, decisions

    return _apply(topology, decisions, scan.files_read), decisions


def _apply(
    topology: RepositoryTopology, decisions: Iterable[Decision], files_read: Iterable[str]
) -> RepositoryTopology:
    internal = list(topology.internal)
    externals = list(topology.externals)
    seen_internal = {(d.source_path, d.target_ref.lower()) for d in internal}
    seen_external = {(e.source_path, canonical_key(e.name)) for e in externals}
    for d in decisions:
        if d.band != "confirmed" or not d.drawn:
            continue
        source = d.candidate.source_path
        label = d.edge_kind or ""
        if d.target_ref:
            key = (source, d.target_ref.lower())
            if key not in seen_internal:
                seen_internal.add(key)
                internal.append(InternalDependency(source, d.target_ref, label=label))
        elif d.external_name:
            key = (source, canonical_key(d.external_name))
            if key not in seen_external:
                seen_external.add(key)
                externals.append(ExternalLink(source, d.external_name, OUTBOUND, "", label))

    evidence = topology.evidence
    merged = list(evidence.files_read)
    known = set(merged)
    for path in files_read:
        if path not in known:
            known.add(path)
            merged.append(path)
    return replace(
        topology,
        internal=tuple(internal),
        externals=tuple(externals),
        evidence=replace(evidence, files_read=tuple(merged)),
    )


class LinkEnrichedInference:
    """A ``TopologyInference`` that runs ``inner`` and then the Jev link stage.
    ``decisions`` holds the last run's decisions for the eval commands."""

    def __init__(
        self,
        inner: TopologyInference,
        jev,
        *,
        thresholds: Thresholds = Thresholds(),
        max_candidates: int | None = None,
        workers: int = 8,
    ):
        self._inner = inner
        self._jev = jev
        self._thresholds = thresholds
        self._max_candidates = max_candidates
        self._workers = workers
        self.decisions: list[Decision] = []

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> RepositoryTopology:
        topology = self._inner.infer(snapshot, context)
        limit = self._max_candidates
        if limit is None:
            limit = getattr(settings, "JEV_MAP_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES)
        enriched, self.decisions = enrich_with_links(
            topology, snapshot, context, self._jev,
            thresholds=self._thresholds, max_candidates=limit, workers=self._workers,
        )
        return enriched
