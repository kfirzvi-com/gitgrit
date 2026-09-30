"""The Jev link stage: questions, the decision table, and the enrichment
wrapper. Pure — a fake Jev, an in-memory snapshot, a fixed inner inference.

``SimpleTestCase`` because CI runs ``manage.py test`` and its loader only
sees TestCase subclasses.
"""
from __future__ import annotations

import json
from dataclasses import replace

from django.test import SimpleTestCase, override_settings

from app.application.architecture.ports import InferenceContext
from app.domain.architecture.links import LinkCandidate, LinkScan, TargetOption
from app.domain.architecture.resolve import RosterEntry, resolve_topology
from app.domain.architecture.topology import (
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


class EnrichTests(MonkeyPatchMixin, SimpleTestCase):
    def setUp(self):
        super().setUp()
        self.snapshot = _Snapshot(MONO_FILES)
        self.logs: list[str] = []
        self.context = context(self.logs.append)

    def fake_scan(self, *candidates, files_read=("apps/api-gateway/src/config.ts",)):
        scan = LinkScan(candidates=tuple(candidates), files_read=tuple(files_read))
        self.monkeypatch.setattr(jev_links, "find_link_candidates", lambda *a, **k: scan)

    def test_confirmed_candidate_from_a_real_scan_becomes_an_internal_edge(self):
        jev = FakeJevClient(link_answers())
        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, jev)

        self.assertEqual([d.band for d in decisions], ["confirmed"])
        self.assertEqual(topology.internal, (InternalDependency("apps/api-gateway", AUTH_SIBLING, label="runtime"),))
        self.assertEqual(topology.externals, INNER.externals)
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
        topology, _ = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(link_answers()))
        roster = self.context.roster + tuple(RosterEntry(THIS_REPO, c.path, c.name) for c in topology.components)
        resolved = resolve_topology(topology, roster, this_repo=THIS_REPO)
        self.assertEqual(
            [(r.source_path, r.target.ref, r.label) for r in resolved.internal],
            [("apps/api-gateway", AUTH_SIBLING, "runtime")],
        )

    def test_already_covered_candidate_is_not_sent_to_jev(self):
        covered = replace(INNER, internal=(InternalDependency("apps/api-gateway", "#services/auth-service", "REST"),))
        jev = FakeJevClient(link_answers())
        topology, decisions = enrich_with_links(covered, self.snapshot, self.context, jev)
        self.assertEqual(jev.calls, [])
        self.assertEqual(decisions, [])
        self.assertEqual(topology, covered)

    def test_same_edge_confirmed_twice_is_added_once(self):
        compose = replace(
            CANDIDATE, file="docker-compose.yml", reference="auth-service", reference_kind="compose_depends_on"
        )
        self.fake_scan(CANDIDATE, compose)
        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(link_answers()))
        self.assertEqual([d.band for d in decisions], ["confirmed", "confirmed"])
        self.assertEqual(len(topology.internal), 1)

    def test_external_and_never_drawn_and_unsure(self):
        self.fake_scan(CANDIDATE, STRIPE)

        def by_reference(state, questions):
            if state["reference"] == "api.stripe.com":
                return link_answers("external")
            return link_answers(kind="test")  # confirmed, but never drawn

        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(by_reference))
        self.assertEqual([(d.band, d.drawn) for d in decisions], [("confirmed", False), ("confirmed", True)])
        self.assertEqual(topology.internal, ())
        self.assertEqual(topology.externals[-1], ExternalLink("apps/api-gateway", "stripe", "outbound", "", "runtime"))

        self.fake_scan(CANDIDATE)
        unsure = FakeJevClient(link_answers(p=0.6))
        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, unsure)
        self.assertEqual({d.band for d in decisions}, {"unsure"})
        self.assertEqual(topology.internal, ())
        self.assertEqual(topology.externals, INNER.externals)

    def test_unknown_edge_kind_is_drawn_without_a_label(self):
        jev = FakeJevClient(link_answers(kind="sideways"))
        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, jev)
        self.assertEqual([(d.band, d.edge_kind, d.drawn) for d in decisions], [("confirmed", None, True)])
        self.assertEqual(topology.internal, (InternalDependency("apps/api-gateway", AUTH_SIBLING, label=""),))

    def test_candidate_outside_the_declared_components_gets_the_stand_in_component(self):
        stray = replace(CANDIDATE, source_path="apps/other", file="apps/other/config.ts")
        self.fake_scan(stray)
        jev = FakeJevClient(link_answers())
        enrich_with_links(INNER, self.snapshot, self.context, jev)
        self.assertEqual(jev.calls[0][0]["source_component"], {"name": "other", "path": "apps/other", "kind": "other"})
        self.assertEqual(jev.calls[0][0], build_state(stray, component_for(stray)))  # what the eval sends too

    def test_more_than_a_fifth_failed_leaves_the_topology_unchanged(self):
        others = [replace(CANDIDATE, reference=f"SVC{i}_URL") for i in range(3)]
        self.fake_scan(CANDIDATE, *others)  # 4 asked, 1 failed = 25 %

        def flaky(state, questions):
            if state["reference"] == "SVC0_URL":
                raise JevError("boom")
            return link_answers()

        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(flaky))
        self.assertEqual(sorted(d.band for d in decisions), ["confirmed", "confirmed", "confirmed", "failed"])
        self.assertEqual(topology, INNER)
        self.assertTrue(any("disabled for this run: 1/4 failed" in m for m in self.logs))

    def test_one_in_ten_failing_still_adds_the_rest(self):
        others = [replace(CANDIDATE, reference=f"SVC{i}_URL") for i in range(9)]
        self.fake_scan(CANDIDATE, *others)

        def flaky(state, questions):
            if state["reference"] == "SVC0_URL":
                raise JevError("boom")
            return link_answers()

        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(flaky))
        self.assertEqual(sum(1 for d in decisions if d.band == "failed"), 1)
        self.assertEqual(len(topology.internal), 1)  # all confirm the same edge

    def test_jev_raising_on_every_call_returns_the_inner_topology(self):
        jev = FakeJevClient(raise_on=JevError("down"))
        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, jev)
        self.assertEqual(topology, INNER)
        self.assertEqual([d.band for d in decisions], ["failed"])

    def test_a_crashing_client_or_scanner_never_raises(self):
        class Broken:
            usage = {"calls": 0, "input_tokens": 0, "failures": 0}

            def ask_many(self, items, *, workers=8):
                raise RuntimeError("client bug")

        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, Broken())
        self.assertEqual((topology, decisions), (INNER, []))
        self.assertTrue(any("jev-links skipped: RuntimeError" in m for m in self.logs))

        self.monkeypatch.setattr(jev_links, "find_link_candidates", lambda *a, **k: 1 / 0)
        topology, _ = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(link_answers()))
        self.assertEqual(topology, INNER)

    def test_no_candidates_leaves_the_topology_unchanged(self):
        self.fake_scan()
        topology, decisions = enrich_with_links(INNER, self.snapshot, self.context, FakeJevClient(link_answers()))
        self.assertEqual((topology, decisions), (INNER, []))

    def test_inner_that_read_nothing_is_not_enriched_so_the_evidence_gate_still_fires(self):
        ungrounded = replace(INNER, evidence=Evidence(tree_size=4, files_read=()))
        jev = FakeJevClient(link_answers())
        topology, decisions = enrich_with_links(ungrounded, self.snapshot, self.context, jev)
        self.assertEqual(topology, ungrounded)
        self.assertEqual(jev.calls, [])
        with self.assertRaises(UngroundedTopology):
            check_evidence(topology.evidence)


class LinkEnrichedInferenceTests(MonkeyPatchMixin, SimpleTestCase):
    def test_wraps_inner_and_keeps_last_decisions(self):
        inner = FakeTopologyInference(INNER, read_files=False)
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

    def test_jev_failure_returns_inner_topology_equal(self):
        inner = FakeTopologyInference(INNER, read_files=False)
        inference = LinkEnrichedInference(inner, FakeJevClient(raise_on=JevError("down")))
        self.assertEqual(inference.infer(_Snapshot(MONO_FILES), context()), INNER)
