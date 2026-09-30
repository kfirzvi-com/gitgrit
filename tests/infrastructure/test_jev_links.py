"""The Jev link stage: questions, the decision table, the enrichment
wrapper and the plan §9 reconcile of the LLM's edges (verdicts). Pure — a
fake Jev, a fake evidence finder, an in-memory snapshot, a fixed inner
inference.

``SimpleTestCase`` because CI runs ``manage.py test`` and its loader only
sees TestCase subclasses.
"""
from __future__ import annotations

import json
from dataclasses import replace

from django.test import SimpleTestCase, override_settings

from app.application.architecture.ports import InferenceContext
from app.domain.architecture.links import EVIDENCE_KIND, LinkCandidate, LinkScan, TargetOption
from app.domain.architecture.resolve import RosterEntry, resolve_topology
from app.domain.architecture.topology import (
    INBOUND,
    ComponentDecl,
    Evidence,
    ExternalLink,
    InternalDependency,
    RepositoryTopology,
    UngroundedTopology,
    check_evidence,
)
from app.infrastructure.topology import jev_links
from app.infrastructure.topology.fake import FakeTopologyInference
from app.infrastructure.topology.jev_links import (
    BANDS,
    EDGE_KINDS,
    NEVER_DRAWN,
    VERDICTS,
    LinkEnrichedInference,
    Thresholds,
    build_questions,
    build_state,
    component_for,
    decide,
    decide_all,
    enrich_with_links,
)
from tests.jev_support import FakeJevClient, JevError, JevResult, link_answers
from tests.support import MonkeyPatchMixin

THIS_REPO = "org/mono"
AUTH_SIBLING = f"{THIS_REPO}#services/auth-service"
GATEWAY = ComponentDecl("apps/api-gateway", "api-gateway", "service")
AUTH = ComponentDecl("services/auth-service", "auth-service", "service")

OPTIONS = (
    TargetOption("A", AUTH_SIBLING, "auth-service", "service"),
    TargetOption("B", "org/auth-service", "auth-service", "component"),
)
CANDIDATE = LinkCandidate(
    source_path="apps/api-gateway",
    file="apps/api-gateway/src/config.ts",
    line=2,
    code="auth: process.env.AUTH_SERVICE_URL,",
    reference="AUTH_SERVICE_URL",
    reference_kind="env_var",
    options=OPTIONS,
)
STRIPE = LinkCandidate(
    source_path="apps/api-gateway",
    file="apps/api-gateway/src/pay.ts",
    line=1,
    code="fetch('https://api.stripe.com/v1/charges')",
    reference="api.stripe.com",
    reference_kind="url",
    options=(),
    external_name="stripe",
)


def result(choice="A", **kw) -> JevResult:
    return JevResult(model="jev-test", answers=link_answers(choice, **kw), input_tokens=500, latency_ms=120)


# --- Questions and state ------------------------------------------------------------------


class BuildQuestionsTests(SimpleTestCase):
    def test_constants(self):
        self.assertEqual(BANDS, ("confirmed", "unsure", "dropped", "failed"))
        self.assertEqual(EDGE_KINDS, ("runtime", "build", "test", "dev_only", "optional"))
        self.assertEqual(NEVER_DRAWN, {"test", "dev_only"})
        self.assertEqual(VERDICTS, ("kept", "moved", "removed", "no_evidence"))

    def test_target_criteria_are_option_ids_plus_external_and_none(self):
        q = build_questions(CANDIDATE)
        self.assertEqual(set(q), {"target", "runtime_call", "inactive", "edge_kind"})
        criteria = q["target"].model_dump()["criteria"]
        self.assertEqual(list(criteria), ["A", "B", "external", "none"])
        self.assertEqual(criteria["A"], f"auth-service ({AUTH_SIBLING})")
        self.assertIn("another company", criteria["external"])
        self.assertIn("library", criteria["none"])
        self.assertEqual(list(q["edge_kind"].model_dump()["criteria"]), list(EDGE_KINDS))
        self.assertEqual(q["runtime_call"].model_dump()["type"], "noul")
        self.assertEqual(q["inactive"].model_dump()["type"], "noul")

    def test_no_options_leaves_only_external_and_none(self):
        criteria = build_questions(STRIPE)["target"].model_dump()["criteria"]
        self.assertEqual(list(criteria), ["external", "none"])
        self.assertIn("empty", build_questions(STRIPE)["target"].model_dump()["instructions"])

    def test_state_shape(self):
        state = build_state(CANDIDATE, GATEWAY)
        self.assertEqual(
            state,
            {
                "source_component": {"name": "api-gateway", "path": "apps/api-gateway", "kind": "service"},
                "file": "apps/api-gateway/src/config.ts",
                "reference": "AUTH_SERVICE_URL",
                "reference_kind": "env_var",
                "code": "auth: process.env.AUTH_SERVICE_URL,",
                "candidates": {
                    "A": {"ref": AUTH_SIBLING, "name": "auth-service", "kind": "service"},
                    "B": {"ref": "org/auth-service", "name": "auth-service", "kind": "component"},
                },
            },
        )
        json.dumps(state)  # JSON-able

    def test_component_for_prefers_the_declared_component_else_a_named_stand_in(self):
        self.assertIs(component_for(CANDIDATE, (AUTH, GATEWAY)), GATEWAY)
        self.assertEqual(component_for(CANDIDATE, (AUTH,)), ComponentDecl("apps/api-gateway", "api-gateway", "other"))
        self.assertEqual(component_for(replace(CANDIDATE, source_path="")), ComponentDecl("", "root", "other"))


# --- Decision table --------------------------------------------------------------------------


class DecideTests(SimpleTestCase):
    def test_default_thresholds(self):
        self.assertEqual((Thresholds().confirm, Thresholds().unsure), (0.60, 0.25))

    def test_confirmed_roster_target(self):
        d = decide(CANDIDATE, result())
        self.assertEqual(d.band, "confirmed")
        self.assertAlmostEqual(d.link, 0.95 * 0.95 * 0.98)
        self.assertEqual(
            (d.target_ref, d.external_name, d.edge_kind, d.drawn, d.choice), (AUTH_SIBLING, "", "runtime", True, "A")
        )

    def test_link_is_p_target_times_runtime_times_not_inactive(self):
        d = decide(CANDIDATE, result(p=0.5, runtime=0.3, inactive=0.1))  # 0.135: well under unsure 0.25
        self.assertAlmostEqual(d.link, 0.135)
        self.assertEqual((d.band, d.target_ref, d.drawn), ("dropped", None, False))

    def test_unsure_band_between_cutoffs(self):
        d = decide(CANDIDATE, result(p=0.45))  # 0.45 × 0.95 × 0.98 ≈ 0.42: between unsure 0.25 and confirm 0.60
        self.assertAlmostEqual(d.link, 0.419, places=3)
        self.assertEqual(d.band, "unsure")
        self.assertIsNone(d.target_ref)
        self.assertFalse(d.drawn)

    def test_a_score_on_a_cutoff_is_inside_the_upper_band(self):
        on_confirm = result(p=0.6, runtime=1.0, inactive=0.0)  # link == 0.60 exactly
        self.assertEqual((decide(CANDIDATE, on_confirm).link, decide(CANDIDATE, on_confirm).band), (0.60, "confirmed"))
        on_unsure = result(p=0.25, runtime=1.0, inactive=0.0)  # link == 0.25 exactly
        self.assertEqual((decide(CANDIDATE, on_unsure).link, decide(CANDIDATE, on_unsure).band), (0.25, "unsure"))

    def test_custom_thresholds(self):
        high = result(p=0.7, runtime=0.9, inactive=0.0)  # 0.63: confirmed by default
        self.assertEqual(decide(CANDIDATE, high).band, "confirmed")
        self.assertEqual(decide(CANDIDATE, high, Thresholds(confirm=0.8, unsure=0.5)).band, "unsure")
        mid = result(p=0.5, runtime=0.9, inactive=0.0)  # 0.45: unsure by default
        self.assertEqual(decide(CANDIDATE, mid).band, "unsure")
        self.assertEqual(decide(CANDIDATE, mid, Thresholds(confirm=0.4, unsure=0.1)).band, "confirmed")
        low = result(p=0.5, runtime=0.3, inactive=0.1)  # 0.135: dropped by default
        self.assertEqual(decide(CANDIDATE, low).band, "dropped")
        self.assertEqual(decide(CANDIDATE, low, Thresholds(confirm=0.4, unsure=0.1)).band, "unsure")

    def test_low_target_confidence_between_two_roster_options_is_unsure(self):
        r = result(confidence=0.4, probabilities={"A": 0.95, "B": 0.05})
        d = decide(CANDIDATE, r)
        self.assertEqual(d.band, "unsure")
        # …but not when there is only one roster option to confuse it with.
        single = replace(CANDIDATE, options=OPTIONS[:1])
        self.assertEqual(decide(single, r).band, "confirmed")

    def test_none_choice_is_dropped_with_a_zero_score_whatever_the_probabilities(self):
        d = decide(CANDIDATE, result("none", p=0.99, runtime=0.99, inactive=0.0))
        self.assertEqual(
            (d.band, d.link, d.target_ref, d.external_name, d.drawn, d.choice),
            ("dropped", 0.0, None, "", False, "none"),
        )

    def test_external_with_a_code_derived_name_is_confirmed_as_external(self):
        d = decide(STRIPE, result("external"))
        self.assertEqual((d.band, d.target_ref, d.external_name, d.drawn), ("confirmed", None, "stripe", True))

    def test_external_without_a_name_is_dropped_with_a_zero_score(self):
        d = decide(CANDIDATE, result("external"))
        self.assertEqual((d.band, d.link, d.external_name, d.drawn), ("dropped", 0.0, "", False))

    def test_never_drawn_kinds_keep_the_band_but_are_not_drawn(self):
        for kind in ("test", "dev_only"):
            d = decide(CANDIDATE, result(kind=kind))
            self.assertEqual((d.band, d.drawn, d.edge_kind), ("confirmed", False, kind), kind)
        self.assertTrue(decide(CANDIDATE, result(kind="build")).drawn)

    def test_unknown_edge_kind_is_none_and_still_drawn(self):
        d = decide(CANDIDATE, result(kind="sideways"))
        self.assertEqual((d.band, d.edge_kind, d.drawn), ("confirmed", None, True))

    def test_unknown_option_id_or_missing_answer_is_failed(self):
        self.assertEqual(decide(CANDIDATE, result("Z")).band, "failed")
        partial = JevResult(
            model="jev-test", answers={"target": link_answers()["target"]}, input_tokens=1, latency_ms=1
        )
        d = decide(CANDIDATE, partial)
        self.assertEqual(d.band, "failed")
        self.assertIn("missing answers", d.error)

    def test_to_log_is_json_and_carries_the_audit_fields_but_never_the_snippet(self):
        log = decide(CANDIDATE, result()).to_log()
        text = json.dumps(log)
        for key in ("band", "link", "target_ref", "edge_kind", "drawn", "choice", "reference", "file"):
            self.assertIn(key, log)
        self.assertEqual(log["jev"]["model"], "jev-test")
        self.assertEqual(log["jev"]["input_tokens"], 500)
        self.assertIn('"probabilities"', text)
        self.assertNotIn("code", log)
        self.assertNotIn(CANDIDATE.code, text)
        # A scanned candidate carries no verdict; it stands for one Jev call.
        self.assertEqual((log["verdict"], log["claimed_target"], log["asked"]), (None, None, True))

    def test_decide_all_maps_results_errors_and_gaps_by_position(self):
        candidates = [CANDIDATE, STRIPE, replace(CANDIDATE, reference="OTHER_URL")]
        decisions = decide_all(candidates, {0: result(), 1: JevError("boom")})
        self.assertEqual([d.candidate for d in decisions], candidates)
        self.assertEqual([d.band for d in decisions], ["confirmed", "failed", "failed"])
        self.assertEqual([d.error for d in decisions], ["", "boom", "no answer"])
        self.assertEqual(decide_all([CANDIDATE], {0: JevError("")})[0].error, "no answer")


# --- Enrichment ------------------------------------------------------------------------------


class _Snapshot:
    def __init__(self, files: dict[str, str]):
        self.files = files

    def list_files(self):
        return list(self.files)

    def read_file(self, path):
        return self.files.get(path)


MONO_FILES = {
    "README.md": "# mono\n",
    "apps/api-gateway/package.json": '{"name": "api-gateway"}',
    "apps/api-gateway/src/config.ts": "export const cfg = {\n  auth: process.env.AUTH_SERVICE_URL,\n};\n",
    "services/auth-service/pyproject.toml": "[project]\nname = 'auth'\n",
}
INNER = RepositoryTopology(
    components=(GATEWAY, AUTH),
    externals=(ExternalLink("services/auth-service", "Auth0"),),
    evidence=Evidence(tree_size=4, files_read=("README.md",)),
)


def context(log=None) -> InferenceContext:
    roster = (
        RosterEntry("org/orders", "", "orders", component_id=1),
        RosterEntry("org/auth-service", "", "auth-service", component_id=2),
    )
    return InferenceContext(project_name="mono", full_path=THIS_REPO, roster=roster, log=log or (lambda m: None))


def no_evidence(tree, read_file, component, tokens, options, external_name="", *, this_repo, components=()):
    return None


class Finder:
    """A fake ``links.find_evidence``: remembers every call and answers with
    ``found(component, tokens, options, external_name)`` (None by default)."""

    def __init__(self, found=None):
        self.found = found or (lambda *a: None)
        self.calls: list[tuple] = []

    def __call__(self, tree, read_file, component, tokens, options, external_name="", *, this_repo, components=()):
        self.calls.append((component.path, tuple(tokens), tuple(options), external_name, this_repo))
        return self.found(component, tuple(tokens), tuple(options), external_name)


def evidence(component, tokens, options, external_name="") -> LinkCandidate:
    """The candidate a real finder builds: the first token, in a file of the component."""
    return LinkCandidate(
        source_path=component.path,
        file=f"{component.path}/src/config.ts",
        line=1,
        code=f"url: process.env.{tokens[0].upper()}_URL,",
        reference=tokens[0],
        reference_kind=EVIDENCE_KIND,
        options=tuple(options),
        external_name=external_name,
    )


class EnrichTests(MonkeyPatchMixin, SimpleTestCase):
    """The additive behaviour (confirmed candidates are added, failures never
    break the map). ``verify`` is False here — the pre-§9 mode — and True in
    the subclass, which must add the same edges."""

    verify = False
    inner = INNER

    def setUp(self):
        super().setUp()
        self.snapshot = _Snapshot(MONO_FILES)
        self.logs: list[str] = []
        self.context = context(self.logs.append)

    def enrich(self, jev, topology=None, **kw):
        return enrich_with_links(
            self.inner if topology is None else topology, self.snapshot, self.context, jev,
            verify_llm_edges=self.verify, evidence_finder=no_evidence, **kw,
        )

    def fake_scan(self, *candidates, files_read=("apps/api-gateway/src/config.ts",)):
        scan = LinkScan(candidates=tuple(candidates), files_read=tuple(files_read))
        self.monkeypatch.setattr(jev_links, "find_link_candidates", lambda *a, **k: scan)

    def test_confirmed_candidate_from_a_real_scan_becomes_an_internal_edge(self):
        jev = FakeJevClient(link_answers())
        topology, decisions = self.enrich(jev)

        self.assertEqual([d.band for d in decisions], ["confirmed"])
        self.assertEqual(topology.internal, (InternalDependency("apps/api-gateway", AUTH_SIBLING, label="runtime"),))
        self.assertEqual(topology.externals, self.inner.externals)
        # Jev saw the shortlist with the sibling first and both fallbacks.
        state, questions = jev.calls[0]
        self.assertEqual(state["reference"], "AUTH_SERVICE_URL")
        self.assertEqual(state["candidates"]["A"]["ref"], AUTH_SIBLING)
        self.assertEqual(list(questions["target"].model_dump()["criteria"]), ["A", "B", "external", "none"])
        # Files the scanner opened join the evidence, after the inner's own, deduped.
        self.assertEqual(topology.evidence.files_read[0], "README.md")
        self.assertIn("apps/api-gateway/src/config.ts", topology.evidence.files_read)
        self.assertEqual(len(set(topology.evidence.files_read)), len(topology.evidence.files_read))
        self.assertEqual(topology.evidence.tree_size, 4)
        # One JSON line per decision.
        lines = [m for m in self.logs if m.startswith("jev-link ")]
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0][len("jev-link "):])["band"], "confirmed")

    def test_confirmed_edge_survives_resolve_topology(self):
        topology, _ = self.enrich(FakeJevClient(link_answers()))
        roster = self.context.roster + tuple(RosterEntry(THIS_REPO, c.path, c.name) for c in topology.components)
        resolved = resolve_topology(topology, roster, this_repo=THIS_REPO)
        self.assertEqual(
            [(r.source_path, r.target.ref, r.label) for r in resolved.internal],
            [("apps/api-gateway", AUTH_SIBLING, "runtime")],
        )

    def test_already_covered_candidate_is_not_sent_to_jev(self):
        covered = replace(self.inner, internal=(InternalDependency("apps/api-gateway", "#services/auth-service", "REST"),))
        jev = FakeJevClient(link_answers())
        topology, decisions = self.enrich(jev, covered)
        self.assertEqual(jev.calls, [])
        self.assertEqual(decisions, [])
        self.assertEqual(topology, covered)

    def test_same_edge_confirmed_twice_is_added_once(self):
        compose = replace(
            CANDIDATE, file="docker-compose.yml", reference="auth-service", reference_kind="compose_depends_on"
        )
        self.fake_scan(CANDIDATE, compose)
        topology, decisions = self.enrich(FakeJevClient(link_answers()))
        self.assertEqual([d.band for d in decisions], ["confirmed", "confirmed"])
        self.assertEqual(len(topology.internal), 1)

    def test_external_and_never_drawn_and_unsure(self):
        self.fake_scan(CANDIDATE, STRIPE)

        def by_reference(state, questions):
            if state["reference"] == "api.stripe.com":
                return link_answers("external")
            return link_answers(kind="test")  # confirmed, but never drawn

        topology, decisions = self.enrich(FakeJevClient(by_reference))
        self.assertEqual([(d.band, d.drawn) for d in decisions], [("confirmed", False), ("confirmed", True)])
        self.assertEqual(topology.internal, ())
        self.assertEqual(topology.externals[-1], ExternalLink("apps/api-gateway", "stripe", "outbound", "", "runtime"))

        self.fake_scan(CANDIDATE)
        unsure = FakeJevClient(link_answers(p=0.6))
        topology, decisions = self.enrich(unsure)
        self.assertEqual({d.band for d in decisions}, {"unsure"})
        self.assertEqual(topology.internal, ())
        self.assertEqual(topology.externals, self.inner.externals)

    def test_unknown_edge_kind_is_drawn_without_a_label(self):
        jev = FakeJevClient(link_answers(kind="sideways"))
        topology, decisions = self.enrich(jev)
        self.assertEqual([(d.band, d.edge_kind, d.drawn) for d in decisions], [("confirmed", None, True)])
        self.assertEqual(topology.internal, (InternalDependency("apps/api-gateway", AUTH_SIBLING, label=""),))

    def test_candidate_outside_the_declared_components_gets_the_stand_in_component(self):
        stray = replace(CANDIDATE, source_path="apps/other", file="apps/other/config.ts")
        self.fake_scan(stray)
        jev = FakeJevClient(link_answers())
        self.enrich(jev)
        self.assertEqual(jev.calls[0][0]["source_component"], {"name": "other", "path": "apps/other", "kind": "other"})
        self.assertEqual(jev.calls[0][0], build_state(stray, component_for(stray)))  # what the eval sends too

    def test_more_than_a_fifth_failed_leaves_the_topology_unchanged(self):
        others = [replace(CANDIDATE, reference=f"SVC{i}_URL") for i in range(3)]
        self.fake_scan(CANDIDATE, *others)  # 4 asked, 1 failed = 25 %

        def flaky(state, questions):
            if state["reference"] == "SVC0_URL":
                raise JevError("boom")
            return link_answers()

        topology, decisions = self.enrich(FakeJevClient(flaky))
        self.assertEqual(sorted(d.band for d in decisions), ["confirmed", "confirmed", "confirmed", "failed"])
        self.assertEqual(topology, self.inner)
        self.assertTrue(any("disabled for this run: 1/4 failed" in m for m in self.logs))

    def test_one_in_ten_failing_still_adds_the_rest(self):
        others = [replace(CANDIDATE, reference=f"SVC{i}_URL") for i in range(9)]
        self.fake_scan(CANDIDATE, *others)

        def flaky(state, questions):
            if state["reference"] == "SVC0_URL":
                raise JevError("boom")
            return link_answers()

        topology, decisions = self.enrich(FakeJevClient(flaky))
        self.assertEqual(sum(1 for d in decisions if d.band == "failed"), 1)
        self.assertEqual(len(topology.internal), 1)  # all confirm the same edge

    def test_jev_raising_on_every_call_returns_the_inner_topology(self):
        jev = FakeJevClient(raise_on=JevError("down"))
        topology, decisions = self.enrich(jev)
        self.assertEqual(topology, self.inner)
        self.assertEqual([d.band for d in decisions], ["failed"])

    def test_a_crashing_client_or_scanner_never_raises(self):
        class Broken:
            usage = {"calls": 0, "input_tokens": 0, "failures": 0}

            def ask_many(self, items, *, workers=8):
                raise RuntimeError("client bug")

        topology, decisions = self.enrich(Broken())
        self.assertEqual((topology, decisions), (self.inner, []))
        self.assertTrue(any("jev-links skipped: RuntimeError" in m for m in self.logs))

        self.monkeypatch.setattr(jev_links, "find_link_candidates", lambda *a, **k: 1 / 0)
        topology, _ = self.enrich(FakeJevClient(link_answers()))
        self.assertEqual(topology, self.inner)

    def test_no_candidates_leaves_the_topology_unchanged(self):
        self.fake_scan()
        topology, decisions = self.enrich(FakeJevClient(link_answers()))
        self.assertEqual((topology, decisions), (self.inner, []))

    def test_inner_that_read_nothing_is_not_enriched_so_the_evidence_gate_still_fires(self):
        ungrounded = replace(self.inner, evidence=Evidence(tree_size=4, files_read=()))
        jev = FakeJevClient(link_answers())
        topology, decisions = self.enrich(jev, ungrounded)
        self.assertEqual(topology, ungrounded)
        self.assertEqual(jev.calls, [])
        with self.assertRaises(UngroundedTopology):
            check_evidence(topology.evidence)


class EnrichVerifyModeTests(EnrichTests):
    """Every additive test again with ``verify_llm_edges`` on. The inner has
    no LLM edges here (Auth0 would need evidence), so only one behaviour
    changes: a candidate the LLM already drew is asked too, and its verdict
    keeps the edge."""

    verify = True
    inner = replace(INNER, externals=())

    def test_already_covered_candidate_is_not_sent_to_jev(self):
        covered = replace(self.inner, internal=(InternalDependency("apps/api-gateway", "#services/auth-service", "REST"),))
        jev = FakeJevClient(link_answers())
        topology, decisions = self.enrich(jev, covered)
        self.assertEqual(len(jev.calls), 1)
        self.assertEqual([(d.band, d.verdict, d.asked) for d in decisions], [("confirmed", None, True), ("confirmed", "kept", False)])
        self.assertEqual(topology.internal, covered.internal)  # kept as the LLM wrote it, the candidate edge deduped


# --- Plan §9: verdicts on the LLM's edges ---------------------------------------------------

GW = "apps/api-gateway"
SIBLING_EDGE = InternalDependency(GW, "#services/auth-service", "REST")  # resolves to option A
LOOSE_EDGE = InternalDependency(GW, "demo-org/auth-service", "REST")  # resolves to org/auth-service, option B
ORDERS_EDGE = InternalDependency(GW, "org/orders", "events")  # no scanned candidate covers it
AUTH0 = ExternalLink("services/auth-service", "Auth0", label="identity")
STRIPE_EXT = ExternalLink(GW, "Stripe API", label="payments")  # covered by the STRIPE candidate
ZAPIER_IN = ExternalLink(GW, "Zapier", INBOUND, label="webhooks")
REDIS = ExternalLink(GW, "Redis")  # resolve_topology turns this into infrastructure
CANDIDATE_EDGE = InternalDependency(GW, AUTH_SIBLING, label="runtime")
ORDERS_OPTION = (TargetOption("A", "org/orders", "orders", "component"),)


def answers_by_reference(**by_reference):
    """A Jev that answers per ``reference`` (``default`` for the rest)."""
    default = by_reference.pop("default", link_answers())

    def answer(state, questions):
        return by_reference.get(state["reference"], default)

    return FakeJevClient(answer)


def found_when(**by_first_token):
    """A finder that builds an evidence candidate when the first token is listed."""

    def found(component, tokens, options, external_name):
        if tokens[0].lower() in by_first_token:
            return evidence(component, tokens, options, external_name)
        return None

    return Finder(found)


class VerifyTests(MonkeyPatchMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.snapshot = _Snapshot(MONO_FILES)
        self.logs: list[str] = []
        self.context = context(self.logs.append)

    def enrich(self, jev, *, internal=(), externals=(), scan=(CANDIDATE,), finder=None, **kw):
        scan = LinkScan(candidates=tuple(scan), files_read=("apps/api-gateway/src/config.ts",))
        self.monkeypatch.setattr(jev_links, "find_link_candidates", lambda *a, **k: scan)
        inner = replace(INNER, internal=tuple(internal), externals=tuple(externals))
        self.finder = finder or Finder()
        return enrich_with_links(
            inner, self.snapshot, self.context, jev, verify_llm_edges=True, evidence_finder=self.finder, **kw
        )

    def verdicts(self, decisions):
        return [(d.verdict, d.claimed_target) for d in decisions if d.verdict]

    # -- the rules table ------------------------------------------------------------

    RULES = [
        # name, inner edges, scan, jev, finder, expected internal, expected externals, expected verdicts
        dict(
            name="kept: covering candidate confirmed with the same target",
            internal=(SIBLING_EDGE,), jev=link_answers(),
            want_internal=(SIBLING_EDGE,), verdicts=[("kept", "#services/auth-service")],
        ),
        dict(
            name="moved: covering candidate confirmed with another option",
            internal=(LOOSE_EDGE,), jev=link_answers("A"),
            want_internal=(CANDIDATE_EDGE,), verdicts=[("moved", "demo-org/auth-service")],
        ),
        dict(
            name="removed: covering candidate dropped",
            internal=(SIBLING_EDGE,), jev=link_answers("none"),
            want_internal=(), verdicts=[("removed", "#services/auth-service")],
        ),
        dict(
            name="removed: covering candidate confirmed as an external instead",
            internal=(SIBLING_EDGE,), scan=(replace(CANDIDATE, external_name="auth0"),), jev=link_answers("external"),
            want_internal=(), want_externals=(ExternalLink(GW, "auth0", "outbound", "", "runtime"),),
            verdicts=[("removed", "#services/auth-service")],
        ),
        dict(
            name="kept: covering candidate unsure",
            internal=(SIBLING_EDGE,), jev=link_answers(p=0.6),
            want_internal=(SIBLING_EDGE,), verdicts=[("kept", "#services/auth-service")],
        ),
        dict(
            name="no_evidence: nothing covers it and the component never names the target",
            internal=(ORDERS_EDGE,), jev=link_answers(),
            want_internal=(CANDIDATE_EDGE,), verdicts=[("no_evidence", "org/orders")],
        ),
        dict(
            name="kept: evidence candidate confirmed",
            internal=(ORDERS_EDGE,), jev=link_answers(), finder=found_when(orders=True),
            want_internal=(ORDERS_EDGE, CANDIDATE_EDGE), verdicts=[("kept", "org/orders")],
        ),
        dict(
            name="removed: evidence candidate dropped",
            internal=(ORDERS_EDGE,), finder=found_when(orders=True),
            jev=answers_by_reference(orders=link_answers("none")),
            want_internal=(CANDIDATE_EDGE,), verdicts=[("removed", "org/orders")],
        ),
        dict(
            name="external kept: covering candidate confirmed external",
            externals=(STRIPE_EXT,), scan=(STRIPE,), jev=link_answers("external"),
            want_externals=(STRIPE_EXT,), verdicts=[("kept", "Stripe API")],
        ),
        dict(
            name="external removed: covering candidate dropped",
            externals=(STRIPE_EXT,), scan=(STRIPE,), jev=link_answers("none"),
            want_externals=(), verdicts=[("removed", "Stripe API")],
        ),
        dict(
            name="external kept: evidence confirmed external",
            externals=(AUTH0,), scan=(), finder=found_when(auth0=True), jev=link_answers("external"),
            want_externals=(AUTH0,), verdicts=[("kept", "Auth0")],
        ),
        dict(
            name="external no_evidence",
            externals=(AUTH0,), scan=(), jev=link_answers("external"),
            want_externals=(), verdicts=[("no_evidence", "Auth0")],
        ),
        dict(
            name="inbound external untouched",
            externals=(ZAPIER_IN,), scan=(), jev=link_answers(),
            want_externals=(ZAPIER_IN,), verdicts=[],
        ),
        dict(
            name="infrastructure-like external untouched",
            externals=(REDIS,), scan=(), jev=link_answers(),
            want_externals=(REDIS,), verdicts=[],
        ),
    ]

    def test_rules_table(self):
        for case in self.RULES:
            with self.subTest(case["name"]):
                jev = case["jev"] if isinstance(case["jev"], FakeJevClient) else FakeJevClient(case["jev"])
                topology, decisions = self.enrich(
                    jev, internal=case.get("internal", ()), externals=case.get("externals", ()),
                    scan=case.get("scan", (CANDIDATE,)), finder=case.get("finder"),
                )
                self.assertEqual(topology.internal, case.get("want_internal", ()))
                self.assertEqual(topology.externals, case.get("want_externals", ()))
                self.assertEqual(self.verdicts(decisions), case["verdicts"])
                self.assertEqual(topology.components, INNER.components)

    def test_moved_edge_points_at_jevs_target_and_survives_resolve_topology(self):
        topology, decisions = self.enrich(FakeJevClient(link_answers("A")), internal=(LOOSE_EDGE,))
        self.assertEqual(topology.internal, (InternalDependency(GW, f"{THIS_REPO}#services/auth-service", "runtime"),))
        roster = self.context.roster + tuple(RosterEntry(THIS_REPO, c.path, c.name) for c in topology.components)
        resolved = resolve_topology(topology, roster, this_repo=THIS_REPO)
        self.assertEqual([(r.source_path, r.target.ref) for r in resolved.internal], [(GW, AUTH_SIBLING)])
        moved = [d for d in decisions if d.verdict == "moved"][0]
        self.assertEqual((moved.target_ref, moved.claimed_target, moved.asked), (AUTH_SIBLING, "demo-org/auth-service", False))

    def test_the_evidence_finder_is_asked_with_the_target_tokens_and_a_same_name_shortlist(self):
        self.enrich(
            FakeJevClient(link_answers()), internal=(ORDERS_EDGE,),
            externals=(AUTH0, ZAPIER_IN, replace(AUTH0, name="Stripe Payments API")),
        )
        self.assertEqual(
            self.finder.calls,
            [
                (GW, ("orders",), ORDERS_OPTION, "", THIS_REPO),
                ("services/auth-service", ("auth0",), (), "auth0", THIS_REPO),  # canonical + raw, deduped
                ("services/auth-service", ("stripe payments", "Stripe Payments API"), (), "stripe payments", THIS_REPO),
            ],
        )
        # A target with a same-named twin elsewhere in the workspace lists both, the resolved one first.
        self.enrich(FakeJevClient(link_answers()), internal=(replace(LOOSE_EDGE, source_path="services/auth-service"),), scan=())
        (_, tokens, options, _, _), = self.finder.calls
        self.assertEqual(tokens, ("auth-service",))
        self.assertEqual([(o.id, o.ref, o.kind) for o in options], [("A", "org/auth-service", "component")])
        self.enrich(FakeJevClient(link_answers()), internal=(LOOSE_EDGE,), scan=())
        (_, _, options, _, _), = self.finder.calls
        self.assertEqual(
            [(o.id, o.ref, o.kind) for o in options],
            [("A", "org/auth-service", "component"), ("B", AUTH_SIBLING, "service")],
        )

    def test_unresolved_targets_and_undeclared_sources_are_left_to_resolve_topology(self):
        ghost = InternalDependency(GW, "org/does-not-exist")
        stray = InternalDependency("apps/nowhere", "org/orders")
        self_loop = InternalDependency(GW, "#apps/api-gateway")
        topology, decisions = self.enrich(FakeJevClient(link_answers()), internal=(ghost, stray, self_loop), scan=())
        self.assertEqual(topology.internal, (ghost, stray, self_loop))
        self.assertEqual((self.finder.calls, self.verdicts(decisions)), ([], []))

    def test_evidence_asks_are_one_extra_batch_after_the_scanned_one(self):
        class Counting(FakeJevClient):
            batches: list[list[str]] = []

            def ask_many(self, items, *, workers=8):
                self.batches.append([state["reference"] for _, state, _ in items])
                return super().ask_many(items, workers=workers)

        jev = Counting(lambda state, q: link_answers("external" if state["reference"] == "auth0" else "A"))
        topology, decisions = self.enrich(
            jev, internal=(SIBLING_EDGE, ORDERS_EDGE), externals=(AUTH0,), finder=found_when(orders=True, auth0=True)
        )
        self.assertEqual(jev.batches, [["AUTH_SERVICE_URL"], ["orders", "auth0"]])
        self.assertEqual(self.verdicts(decisions), [("kept", "#services/auth-service"), ("kept", "org/orders"), ("kept", "Auth0")])
        self.assertEqual(topology.internal, (SIBLING_EDGE, ORDERS_EDGE))
        self.assertEqual(topology.externals, (AUTH0,))
        # Decisions: the scanned candidate, then one verdict per LLM edge; evidence verdicts are asks.
        self.assertEqual([(d.verdict, d.asked) for d in decisions], [(None, True), ("kept", False), ("kept", True), ("kept", True)])

    def test_no_evidence_asks_when_nothing_needs_them(self):
        class Counting(FakeJevClient):
            n = 0

            def ask_many(self, items, *, workers=8):
                self.n += 1
                return super().ask_many(items, workers=workers)

        jev = Counting(link_answers())
        self.enrich(jev, internal=(SIBLING_EDGE,))
        self.assertEqual(jev.n, 1)

    def test_log_lines_carry_the_verdict_and_the_claim_but_never_the_snippet(self):
        self.enrich(FakeJevClient(link_answers("A")), internal=(LOOSE_EDGE, ORDERS_EDGE), finder=found_when(orders=True))
        lines = [json.loads(m[len("jev-link "):]) for m in self.logs if m.startswith("jev-link ")]
        self.assertEqual(
            [(l["verdict"], l["claimed_target"], l["asked"], l["reference_kind"]) for l in lines],
            [(None, None, True, "env_var"), ("moved", "demo-org/auth-service", False, "env_var"), ("kept", "org/orders", True, "evidence")],
        )
        for line in lines:
            self.assertNotIn("code", line)
        self.assertIn("jev-links verdicts: kept 1, moved 1, removed 0, no_evidence 0", self.logs)

    def test_no_evidence_decision_is_logged_without_a_jev_call(self):
        _, decisions = self.enrich(FakeJevClient(link_answers()), internal=(ORDERS_EDGE,))
        d = [d for d in decisions if d.verdict == "no_evidence"][0]
        self.assertEqual((d.band, d.asked, d.result, d.drawn, d.candidate.reference_kind), ("no_evidence", False, None, False, EVIDENCE_KIND))
        json.dumps(d.to_log())

    def test_failed_evidence_asks_count_toward_the_failure_gate(self):
        def flaky(state, questions):
            if state["reference"] == "orders":
                raise JevError("boom")
            return link_answers()

        inner_edges = (ORDERS_EDGE,)
        topology, decisions = self.enrich(FakeJevClient(flaky), internal=inner_edges, finder=found_when(orders=True))
        self.assertEqual(sorted(d.band for d in decisions if d.asked), ["confirmed", "failed"])  # 1/2 failed
        self.assertEqual(topology.internal, inner_edges)  # unchanged: nothing added, nothing removed
        self.assertTrue(any("disabled for this run: 1/2 failed" in m for m in self.logs))

    def test_jev_down_keeps_every_llm_edge(self):
        topology, decisions = self.enrich(FakeJevClient(raise_on=JevError("down")), internal=(SIBLING_EDGE,), externals=(AUTH0,))
        self.assertEqual((topology.internal, topology.externals), ((SIBLING_EDGE,), (AUTH0,)))
        self.assertEqual(self.finder.calls, [])  # no evidence asks are spent on a client that is down

    def test_a_crashing_finder_never_raises(self):
        def broken(*a, **k):
            raise RuntimeError("finder bug")

        topology, _ = self.enrich(FakeJevClient(link_answers()), internal=(ORDERS_EDGE,), finder=broken)
        self.assertEqual(topology.internal, (ORDERS_EDGE,))
        self.assertTrue(any("jev-links skipped: RuntimeError" in m for m in self.logs))


class LinkEnrichedInferenceTests(MonkeyPatchMixin, SimpleTestCase):
    def test_wraps_inner_and_keeps_last_decisions(self):
        inner = FakeTopologyInference(replace(INNER, externals=()), read_files=False)
        jev = FakeJevClient(link_answers())
        inference = LinkEnrichedInference(inner, jev)

        topology = inference.infer(_Snapshot(MONO_FILES), context())

        self.assertEqual(len(topology.internal), 1)
        self.assertEqual([d.band for d in inference.decisions], ["confirmed"])
        self.assertEqual(inner.contexts[0].full_path, THIS_REPO)

    def test_max_candidates_defaults_from_settings(self):
        seen = {}

        def scan(tree, read_file, components, roster, *, this_repo, limit):
            seen["limit"] = limit
            return LinkScan((), ())

        self.monkeypatch.setattr(jev_links, "find_link_candidates", scan)
        inner = FakeTopologyInference(INNER, read_files=False)
        with override_settings(JEV_MAP_MAX_CANDIDATES=7):
            LinkEnrichedInference(inner, FakeJevClient(link_answers())).infer(_Snapshot(MONO_FILES), context())
        self.assertEqual(seen["limit"], 7)
        capped = LinkEnrichedInference(inner, FakeJevClient(link_answers()), max_candidates=3)
        capped.infer(_Snapshot(MONO_FILES), context())
        self.assertEqual(seen["limit"], 3)

    def test_verify_llm_edges_defaults_from_settings(self):
        inner = FakeTopologyInference(replace(INNER, externals=(), internal=(SIBLING_EDGE,)), read_files=False)
        with override_settings(JEV_VERIFY_LLM_EDGES=False):
            jev = FakeJevClient(link_answers())
            LinkEnrichedInference(inner, jev).infer(_Snapshot(MONO_FILES), context())
            self.assertEqual(jev.calls, [])  # additive mode: the covered candidate is skipped
        with override_settings(JEV_VERIFY_LLM_EDGES=True):
            jev = FakeJevClient(link_answers())
            inference = LinkEnrichedInference(inner, jev)
            inference.infer(_Snapshot(MONO_FILES), context())
            self.assertEqual(len(jev.calls), 1)
            self.assertEqual([d.verdict for d in inference.decisions], [None, "kept"])
        jev = FakeJevClient(link_answers())
        LinkEnrichedInference(inner, jev, verify_llm_edges=False).infer(_Snapshot(MONO_FILES), context())
        self.assertEqual(jev.calls, [])

    def test_uses_the_real_evidence_finder_by_default(self):
        # ``links.find_evidence`` on the in-memory files: api-gateway's config names AUTH_SERVICE_URL,
        # which is "auth-service"'s token, so the loose edge gets an evidence ask; nothing names orders.
        inner = FakeTopologyInference(replace(INNER, externals=(), internal=(ORDERS_EDGE,)), read_files=False)
        jev = FakeJevClient(link_answers())
        inference = LinkEnrichedInference(inner, jev)
        topology = inference.infer(_Snapshot(MONO_FILES), context())
        self.assertEqual([d.verdict for d in inference.decisions if d.verdict], ["no_evidence"])
        self.assertNotIn(ORDERS_EDGE, topology.internal)

    def test_jev_failure_returns_inner_topology_equal(self):
        inner = FakeTopologyInference(INNER, read_files=False)
        inference = LinkEnrichedInference(inner, FakeJevClient(raise_on=JevError("down")))
        self.assertEqual(inference.infer(_Snapshot(MONO_FILES), context()), INNER)


class CoversTests(SimpleTestCase):
    """A manifest match covers the LLM's edge to the same-named other repository."""

    def _claim(self, target_ref, tokens):
        from app.infrastructure.topology.jev_links import _Claim

        return _Claim(
            edge=InternalDependency(GW, target_ref, ""), component=GATEWAY, claimed=target_ref,
            target_ref=target_ref, tokens=tokens, options=(), external_name="",
        )

    def test_package_dep_covers_a_claim_with_the_dependency_name(self):
        from app.infrastructure.topology.jev_links import _covers

        shared = TargetOption("A", f"{THIS_REPO}#packages/shared-lib", "shared-lib", "library")
        for reference in ("@gitgrit-demo/shared-lib", "gitgrit-demo-shared-lib", "github.com/org/mono/packages/shared-lib"):
            with self.subTest(reference=reference):
                dep = LinkCandidate(GW, "apps/api-gateway/package.json", 6, "", reference, "package_dep", (shared,), "")
                other_repo = self._claim("org/gitgrit-demo-shared-lib", ("gitgrit-demo-shared-lib", "shared-lib"))
                self.assertTrue(_covers(dep, other_repo))
                unrelated = self._claim("org/orders", ("orders", "orders-service"))
                self.assertFalse(_covers(dep, unrelated))
        env = LinkCandidate(GW, "apps/api-gateway/.env", 1, "", "SHARED_LIB_URL", "env_var", (shared,), "")
        self.assertFalse(_covers(env, self._claim("org/gitgrit-demo-shared-lib", ("gitgrit-demo-shared-lib",))))


class PackageDepDecisionTests(SimpleTestCase):
    """For a manifest-resolved dependency the target is code's fact; Jev only
    says whether the dependency is live."""

    SHARED = TargetOption("A", f"{THIS_REPO}#packages/shared-lib", "shared-lib", "library")

    def _dep(self):
        return LinkCandidate(GW, "services/orders-service/go.mod", 6, "", "github.com/org/mono/packages/shared-lib", "package_dep", (self.SHARED,), "")

    def test_jev_doubting_the_target_does_not_drop_a_live_dependency(self):
        answers = link_answers("none", p=0.51, runtime=0.80, inactive=0.05)
        d = decide(self._dep(), JevResult(model="jev", answers=answers, input_tokens=0, latency_ms=0))
        self.assertEqual((d.band, d.target_ref, d.choice), ("confirmed", self.SHARED.ref, "A"))
        self.assertAlmostEqual(d.link, 0.76, places=2)

    def test_a_dead_dependency_is_still_dropped(self):
        answers = link_answers("A", p=0.9, runtime=0.10, inactive=0.90)
        d = decide(self._dep(), JevResult(model="jev", answers=answers, input_tokens=0, latency_ms=0))
        self.assertEqual(d.band, "dropped")

    def test_only_manifest_matches_get_the_rule(self):
        env = LinkCandidate(GW, "apps/api-gateway/.env", 1, "", "SHARED_LIB_URL", "env_var", (self.SHARED,), "")
        answers = link_answers("none", p=0.51, runtime=0.80, inactive=0.05)
        d = decide(env, JevResult(model="jev", answers=answers, input_tokens=0, latency_ms=0))
        self.assertEqual((d.band, d.link), ("dropped", 0.0))
