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

Plan §9 (``verify_llm_edges``, the default): the LLM is only a proposer. An
edge is on the map when code found evidence for it and Jev confirmed that
evidence, whoever proposed it. Every scanned candidate is judged; then each
LLM edge is reconciled against those judgments (``verdict``):

    kept         a covering candidate was confirmed with the same target, or
                 Jev was unsure (or did not answer) — the edge stays as written
    moved        a covering candidate was confirmed with another option — the
                 edge now points at Jev's target
    removed      the covering candidate was dropped (or Jev said "external"
                 for an internal claim, or a workspace component for an
                 external claim)
    no_evidence  nothing covers it and nothing in the source component even
                 mentions the target — the edge is removed without asking

An LLM edge no scanned candidate covers gets one *evidence candidate*
(``links.find_evidence``: the first line in the component that names the
target), asked in a second ``ask_many`` batch and judged by the same rules.
Inbound externals (systems that call the component) are left untouched:
code has no evidence model for consumers yet. With ``verify_llm_edges``
off the stage is purely additive, as before: candidates already on the map
are skipped and confirmed ones are added.

Jev never fails a map refresh: any exception from the scanner or the client
is caught and logged, and the inner topology is returned unchanged. The same
happens when more than 20 % of the asked candidates failed (a partial run
would bias the map toward whatever happened to answer) and when the inner
inference read no files (the evidence gate must still reject that run).
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from typing import Iterable

from django.conf import settings
from typesafe_sdk import Choice, Noul

from app.application.architecture.ports import (
    InferenceContext,
    RepositorySnapshot,
    TopologyInference,
)
from app.domain.architecture.links import (
    PACKAGE_DEP_KIND,
    DEFAULT_LIMIT,
    EVIDENCE_KIND,
    LinkCandidate,
    TargetOption,
    already_covered,
    find_evidence,
    find_link_candidates,
)
from app.domain.architecture.naming import canonical_key
from app.domain.architecture.resolve import GENERIC_CLOUD, RosterEntry, infra_kind, resolve_ref, with_siblings
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

KEPT, MOVED, REMOVED, NO_EVIDENCE = "kept", "moved", "removed", "no_evidence"
VERDICTS = (KEPT, MOVED, REMOVED, NO_EVIDENCE)
MAX_EVIDENCE_OPTIONS = 6
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
        "not a service run by another party: a general-purpose library or framework that none "
        "of `candidates` publishes, a local file, a database, cache or message broker the "
        "component itself operates, a build tool or package registry, a placeholder, or the "
        "component itself"
    )
    return criteria


def build_questions(candidate: LinkCandidate) -> dict:
    # Jev is literal: every form a reference can take is spelled out, and the
    # two catch-all answers say exactly what falls into them.
    forms = (
        "`reference` may be a service name, a hostname or URL, an environment variable that "
        "holds a service address, a docker-compose service or container image, a queue or "
        "topic name (pick the service that owns or produces it), a client SDK or package "
        "for a service, or a dependency declared in the component's own manifest "
        "(package.json, go.mod, pyproject.toml, Cargo.toml) on a package that one of "
        "`candidates` publishes. "
    )
    if candidate.options:
        target = (
            "Which of `candidates` is the workspace service that `reference` in `code` refers "
            "to? " + forms +
            "Pick `external` if it refers to a third-party service run by another company, "
            "including through that company's SDK or package. Pick `none` if it is not a "
            "service run by another party: a general-purpose library or framework that none "
            "of `candidates` publishes, a local file, a database, cache or broker the "
            "component itself operates, a build tool or package registry, or a placeholder."
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
                "from, a client SDK it installs or imports, a workspace package it declares "
                "as a dependency in its manifest. For an infrastructure-as-code component "
                "(Terraform, Helm, CloudFormation), applying or deploying it is its running: "
                "a remote state, module or resource it reads from another component counts. "
                "Answer no when `reference` is "
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
    # Plan §9. ``verdict`` is set on the decision that settled an LLM edge
    # (one of ``VERDICTS``), None for a scanned candidate; ``claimed_target``
    # is the target as the LLM wrote it. ``asked`` is False for a copy of a
    # covering decision (the same Jev call also stands as a scanned candidate)
    # and for a ``no_evidence`` claim, which never reached Jev.
    verdict: str | None = None
    claimed_target: str | None = None
    asked: bool = True

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
            "verdict": self.verdict,
            "claimed_target": self.claimed_target,
            "asked": self.asked,
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

    if candidate.reference_kind == PACKAGE_DEP_KIND and len(candidate.options) == 1 and choice != EXTERNAL:
        # The manifest resolved this dependency to the sibling (by package name
        # or path), so the target is code's fact, not Jev's call: only "is the
        # dependency live" is scored. Jev doubting whether a module path like
        # ``github.com/org/monorepo/packages/x`` is the sibling ``x`` is fair,
        # and irrelevant.
        choice = candidate.options[0].id
        target = replace(target, choice=choice, probabilities={choice: 1.0}, confidence=1.0)

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
    verify_llm_edges: bool = True,
    evidence_finder=None,
) -> tuple[RepositoryTopology, list[Decision]]:
    """Add Jev-confirmed links to ``topology`` and, with ``verify_llm_edges``,
    reconcile the LLM's own edges against the evidence (plan §9).
    ``evidence_finder`` defaults to ``links.find_evidence`` (looked up at call
    time so a test can swap it). Never raises: on any failure the inner
    topology comes back unchanged with whatever was decided."""
    decisions: list[Decision] = []
    finder = evidence_finder or find_evidence
    try:
        return _enrich(
            topology, snapshot, context, jev, thresholds, max_candidates, workers, decisions,
            verify_llm_edges, finder,
        )
    except Exception as exc:  # Jev never fails a map refresh
        context.log(f"jev-links skipped: {type(exc).__name__}: {exc}")
        return topology, decisions


def _enrich(topology, snapshot, context, jev, thresholds, max_candidates, workers, decisions, verify, finder) -> tuple:
    if not topology.evidence.files_read:
        context.log("jev-links skipped: the inference read no files")
        return topology, decisions

    roster = with_siblings(context.roster, context.full_path, topology.components)
    tree = list(snapshot.list_files())
    scan = find_link_candidates(
        tree, snapshot.read_file, topology.components, roster, this_repo=context.full_path, limit=max_candidates,
    )
    if verify:
        return _verify(topology, tree, snapshot, context, roster, scan, jev, thresholds, workers, decisions, finder)

    candidates = [c for c in scan.candidates if not already_covered(c, topology)]
    context.log(
        f"jev-links: {len(scan.candidates)} candidates from {len(scan.files_read)} files, "
        f"{len(candidates)} not already on the map"
    )
    if not candidates:
        return topology, decisions

    decisions.extend(_ask(jev, candidates, topology.components, thresholds, workers))
    _log_decisions(context, decisions)
    if _too_many_failed(context, decisions):
        return topology, decisions
    return _apply(topology, decisions, scan.files_read), decisions


def _ask(jev, candidates, components, thresholds, workers) -> list[Decision]:
    """One ``ask_many`` batch over ``candidates``, decided in order."""
    items = [
        (i, build_state(c, component_for(c, components)), build_questions(c)) for i, c in enumerate(candidates)
    ]
    results = jev.ask_many(items, workers=workers)
    return decide_all(candidates, results, thresholds)


def _log_decisions(context, decisions: Iterable[Decision]) -> None:
    for decision in decisions:
        context.log("jev-link " + json.dumps(decision.to_log(), ensure_ascii=False, default=str))


def _too_many_failed(context, decisions: Iterable[Decision]) -> bool:
    asked = [d for d in decisions if d.asked]
    failed = sum(1 for d in asked if d.band == "failed")
    if asked and failed / len(asked) > MAX_FAILURE_SHARE:
        context.log(f"jev-links disabled for this run: {failed}/{len(asked)} failed")
        return True
    return False


# --- Plan §9: reconcile the LLM's edges with the evidence ---------------------------------


@dataclass
class _Claim:
    """One LLM edge under verification and what settles it."""

    edge: InternalDependency | ExternalLink
    component: ComponentDecl
    claimed: str  # the target as the LLM wrote it
    target_ref: str | None  # the resolved roster ref of an internal claim, None for an external one
    tokens: tuple[str, ...]
    options: tuple[TargetOption, ...]
    external_name: str
    verdict: str | None = None
    replacement: InternalDependency | ExternalLink | None = None
    decision: Decision | None = None

    @property
    def is_internal(self) -> bool:
        return isinstance(self.edge, InternalDependency)


def _verify(topology, tree, snapshot, context, roster, scan, jev, thresholds, workers, decisions, finder) -> tuple:
    scanned = _ask(jev, list(scan.candidates), topology.components, thresholds, workers) if scan.candidates else []
    decisions.extend(scanned)
    claims = _claims(topology, roster, context.full_path)
    context.log(
        f"jev-links: {len(scan.candidates)} candidates from {len(scan.files_read)} files, "
        f"{len(claims)} LLM edges to verify"
    )
    if not scanned and not claims:
        return topology, decisions
    if scanned and _too_many_failed(context, decisions):
        _log_decisions(context, scanned)  # Jev is down: do not spend the evidence asks
        return topology, decisions

    pending: list[tuple[_Claim, LinkCandidate]] = []
    for claim in claims:
        covering = [d for d in scanned if _covers(d.candidate, claim)]
        if covering:
            _settle(claim, min((_judge(claim, d) for d in covering), key=lambda j: j[0]))
            continue
        candidate = finder(
            tree, snapshot.read_file, claim.component, claim.tokens, claim.options, claim.external_name,
            this_repo=context.full_path, components=topology.components,
        )
        if candidate is None:
            claim.verdict = NO_EVIDENCE
            claim.decision = _no_evidence_decision(claim)
        else:
            pending.append((claim, candidate))
    if pending:
        # One batch for every evidence ask, after the scanned batch.
        evidence = _ask(jev, [c for _, c in pending], topology.components, thresholds, workers)
        for (claim, _), decision in zip(pending, evidence):
            _settle(claim, _judge(claim, decision))
    verdicts = [claim.decision for claim in claims if claim.decision is not None]
    decisions.extend(verdicts)
    _log_decisions(context, scanned + verdicts)
    if pending and _too_many_failed(context, decisions):
        return topology, decisions

    counts = {v: sum(1 for c in claims if c.verdict == v) for v in VERDICTS}
    context.log("jev-links verdicts: " + ", ".join(f"{v} {n}" for v, n in counts.items()))
    return _apply(topology, scanned, scan.files_read, claims={id(c.edge): c for c in claims}), decisions


def _claims(topology: RepositoryTopology, roster: tuple[RosterEntry, ...], this_repo: str) -> list[_Claim]:
    """The LLM edges the evidence can settle. Left out (untouched, so
    ``resolve_topology`` treats them as today): edges from a path that is not
    a declared component, internal targets nothing in the roster matches,
    self-loops, inbound externals, and externals ``resolve_topology`` would
    reclassify anyway (a workspace component, a bare cloud provider, a
    datastore that becomes infrastructure)."""
    components = {c.path: c for c in topology.components}
    claims: list[_Claim] = []
    for dep in topology.internal:
        component = components.get(dep.source_path)
        entry = resolve_ref(dep.target_ref, roster, this_repo=this_repo)
        if component is None or entry is None:
            continue
        if entry.full_path.lower() == this_repo.lower() and entry.path == dep.source_path:
            continue
        claims.append(
            _Claim(
                edge=dep,
                component=component,
                claimed=dep.target_ref,
                target_ref=entry.ref,
                tokens=_dedupe((entry.name, entry.path.rsplit("/", 1)[-1], entry.full_path.rsplit("/", 1)[-1])),
                options=_evidence_options(entry, roster, dep.source_path, components, this_repo),
                external_name="",
            )
        )
    for ext in topology.externals:
        component = components.get(ext.source_path)
        name = (ext.name or "").strip()
        if component is None or not name or ext.direction != OUTBOUND:
            continue  # inbound: code has no evidence model for consumers yet
        if resolve_ref(name, roster, this_repo=this_repo) or name.lower() in GENERIC_CLOUD or infra_kind(name):
            continue
        canonical = canonical_key(name)
        claims.append(
            _Claim(
                edge=ext,
                component=component,
                claimed=name,
                target_ref=None,
                tokens=_dedupe((canonical, name)),
                options=(),
                external_name=canonical,
            )
        )
    return claims


def _dedupe(tokens: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out = []
    for token in tokens:
        key = (token or "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(token.strip())
    return tuple(out)


def _evidence_options(
    entry: RosterEntry, roster: Iterable[RosterEntry], source_path: str, components: dict, this_repo: str
) -> tuple[TargetOption, ...]:
    """The shortlist for an evidence ask: the resolved entry as ``A`` plus the
    other roster entries with the same name (the ones ``resolve_ref`` may have
    confused it with), at most ``MAX_EVIDENCE_OPTIONS``."""

    def kind(e: RosterEntry) -> str:
        if e.full_path.lower() == this_repo.lower() and e.path in components:
            return components[e.path].kind
        return "component"

    same_name = [
        e for e in roster
        if e.ref != entry.ref
        and e.name.lower() == entry.name.lower()
        and not (e.full_path.lower() == this_repo.lower() and e.path == source_path)
    ]
    options = []
    for e in [entry, *same_name][:MAX_EVIDENCE_OPTIONS]:
        options.append(TargetOption(chr(ord("A") + len(options)), e.ref, e.name, kind(e)))
    return tuple(options)


def _covers(candidate: LinkCandidate, claim: _Claim) -> bool:
    """Does a scanned candidate speak to this claim?

    Same source and the claimed target among its options, or the same
    canonical external name. A ``package_dep`` also covers a claim whose
    target has the dependency's name: the manifest already resolved that
    name to a sibling by package name or path, so an LLM edge that sends
    ``gitgrit-demo-shared-lib`` to the same-named other repository is the
    same claim, and Jev's confirmed sibling then moves it."""
    if candidate.source_path != claim.edge.source_path:
        return False
    if claim.is_internal:
        if any(o.ref.lower() == (claim.target_ref or "").lower() for o in candidate.options):
            return True
        if candidate.reference_kind == PACKAGE_DEP_KIND:
            dep = _name_key(candidate.reference.rstrip("/").rsplit("/", 1)[-1])
            return dep != "" and dep in {_name_key(t) for t in claim.tokens}
        return False
    return bool(candidate.external_name) and canonical_key(candidate.external_name) == claim.external_name


def _name_key(name: str) -> str:
    """``@gitgrit-demo/shared_lib`` and ``gitgrit-demo-shared-lib`` compare by
    their alphanumeric runs."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def _judge(claim: _Claim, decision: Decision) -> tuple[int, str, object, Decision]:
    """The rules table for one decision about ``claim``: ``(rank, verdict,
    replacement, decision)``. The rank orders several covering decisions:
    a confirmation of the claimed target beats a confirmed move, which beats
    an unsure (or unanswered) keep, which beats a removal."""
    band = decision.band
    if claim.is_internal:
        if band == "confirmed" and decision.target_ref:
            if decision.target_ref.lower() == (claim.target_ref or "").lower():
                return (0, KEPT, claim.edge, decision)
            moved = InternalDependency(claim.edge.source_path, decision.target_ref, label=decision.edge_kind or "")
            return (1, MOVED, moved, decision)
    elif band == "confirmed" and decision.external_name:
        return (0, KEPT, claim.edge, decision)
    if band in ("unsure", "failed"):
        return (2, KEPT, claim.edge, decision)
    return (3, REMOVED, None, decision)  # dropped, or confirmed as the other kind of target


def _settle(claim: _Claim, judgment: tuple[int, str, object, Decision]) -> None:
    _, verdict, replacement, decision = judgment
    claim.verdict = verdict
    claim.replacement = replacement
    claim.decision = replace(
        decision,
        verdict=verdict,
        claimed_target=claim.claimed,
        asked=decision.candidate.reference_kind == EVIDENCE_KIND,
    )


def _no_evidence_decision(claim: _Claim) -> Decision:
    placeholder = LinkCandidate(
        source_path=claim.edge.source_path, file="", line=0, code="", reference=claim.claimed,
        reference_kind=EVIDENCE_KIND, options=claim.options, external_name=claim.external_name,
    )
    return Decision(
        candidate=placeholder, band=NO_EVIDENCE, link=0.0, target_ref=None, external_name="",
        edge_kind=None, drawn=False, result=None, verdict=NO_EVIDENCE, claimed_target=claim.claimed, asked=False,
    )


# --- Building the enriched topology --------------------------------------------------------


def _apply(
    topology: RepositoryTopology,
    decisions: Iterable[Decision],
    files_read: Iterable[str],
    claims: dict[int, _Claim] | None = None,
) -> RepositoryTopology:
    """``topology`` with the LLM edges settled by ``claims`` (kept, moved or
    removed; unclaimed edges stay as written) plus the confirmed, drawn
    candidate edges, deduped by (source, target ref) / (source, canonical
    name). Files the scanner opened join the evidence."""
    claims = claims or {}
    internal: list[InternalDependency] = []
    seen_internal: set[tuple[str, str]] = set()
    for dep in topology.internal:
        claim = claims.get(id(dep))
        if claim is None:
            key = (dep.source_path, dep.target_ref.lower())
        elif claim.replacement is None:
            continue  # removed / no_evidence
        else:
            dep = claim.replacement
            key = (dep.source_path, (dep.target_ref if claim.verdict == MOVED else claim.target_ref).lower())
        if key not in seen_internal:
            seen_internal.add(key)
            internal.append(dep)

    externals: list[ExternalLink] = []
    seen_external: set[tuple[str, str]] = set()
    for ext in topology.externals:
        claim = claims.get(id(ext))
        if claim is not None and claim.replacement is None:
            continue
        externals.append(ext)
        if ext.direction == OUTBOUND:
            seen_external.add((ext.source_path, canonical_key(ext.name)))

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
    ``decisions`` holds the last run's decisions for the eval commands (the
    scanned candidates, then one verdict per verified LLM edge).
    ``verify_llm_edges`` and ``max_candidates`` default from the settings
    (``JEV_VERIFY_LLM_EDGES``, ``JEV_MAP_MAX_CANDIDATES``) at ``infer`` time."""

    def __init__(
        self,
        inner: TopologyInference,
        jev,
        *,
        thresholds: Thresholds = Thresholds(),
        max_candidates: int | None = None,
        workers: int = 8,
        verify_llm_edges: bool | None = None,
        evidence_finder=None,
    ):
        self._inner = inner
        self._jev = jev
        self._thresholds = thresholds
        self._max_candidates = max_candidates
        self._workers = workers
        self._verify_llm_edges = verify_llm_edges
        self._evidence_finder = evidence_finder
        self.decisions: list[Decision] = []

    def infer(self, snapshot: RepositorySnapshot, context: InferenceContext) -> RepositoryTopology:
        topology = self._inner.infer(snapshot, context)
        limit = self._max_candidates
        if limit is None:
            limit = getattr(settings, "JEV_MAP_MAX_CANDIDATES", DEFAULT_MAX_CANDIDATES)
        verify = self._verify_llm_edges
        if verify is None:
            verify = getattr(settings, "JEV_VERIFY_LLM_EDGES", True)
        enriched, self.decisions = enrich_with_links(
            topology, snapshot, context, self._jev,
            thresholds=self._thresholds, max_candidates=limit, workers=self._workers,
            verify_llm_edges=verify, evidence_finder=self._evidence_finder,
        )
        return enriched
