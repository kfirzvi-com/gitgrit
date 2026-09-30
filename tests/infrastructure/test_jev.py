"""The Jev client maps SDK answers to plain results, counts usage, and keeps
one bad call from sinking a batch. No network: the SDK's HTTP layer is
``httpx2`` (a vendored httpx fork), so its ``MockTransport`` stands in for
api.typesafe.ai. Retries are turned off so the 5xx test does not sleep.

``SimpleTestCase`` because CI runs ``manage.py test`` and its loader only
sees TestCase subclasses.
"""
from __future__ import annotations

import json

import httpx2
from django.test import SimpleTestCase, override_settings
from typesafe_sdk import (
    Choice,
    Noul,
    RetryPolicy,
    Score,
    TypeSafeAuthenticationError,
    TypeSafeInternalServerError,
)

from app.infrastructure.jev import (
    JevAnswer,
    JevClient,
    JevError,
    JevResult,
    RecordingJevClient,
    cassette_key,
    jev_enabled,
)
from tests.jev_support import FakeJevClient, JevReplayMiss, ReplayJevClient
from tests.support import TmpPathMixin

NO_RETRY = RetryPolicy(max_retries=0)

QUESTIONS = {
    "runtime_call": Noul(instructions="Does the code call the target at runtime?"),
    "target": Choice(instructions="Which one?", criteria={"A": None, "B": None, "none": None}),
    "strength": Score(instructions="How sure?", criteria=["weak", "medium", "strong"]),
}

ANSWERS_BODY = {
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 42, "output_tokens": 3},
    "answers": {
        "runtime_call": {"type": "noul", "noul": 0.91},
        "target": {
            "type": "choice",
            "choice": "A",
            "confidence": 0.7,
            "probabilities": {"A": 0.7, "B": 0.2, "none": 0.1},
        },
        "strength": {
            "type": "score",
            "score": 1.5,
            "confidence": 0.55,
            "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6},
            "legend": {"0": "weak", "1": "medium", "2": "strong"},
        },
    },
}


def client_returning(handler) -> JevClient:
    return JevClient(
        api_key="test-key",
        model="jev-1.13.0",
        timeout=5.0,
        transport=httpx2.MockTransport(handler),
        retry=NO_RETRY,
    )


def always(status: int, body: dict):
    def handler(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(status, json=body)

    return handler


class AskTests(SimpleTestCase):
    def test_maps_noul_choice_and_score_answers(self):
        sent = {}

        def handler(request):
            sent["url"] = str(request.url)
            sent["body"] = json.loads(request.content)
            return httpx2.Response(200, json=ANSWERS_BODY)

        result = client_returning(handler).ask({"file": "a.py"}, QUESTIONS)

        self.assertTrue(sent["url"].endswith("/v1/systemone"))
        self.assertEqual(sent["body"]["model"], "jev-1.13.0")
        self.assertEqual(sent["body"]["state"], {"file": "a.py"})
        self.assertEqual(sent["body"]["questions"]["target"]["type"], "choice")

        self.assertEqual(result.model, "jev-1.13.0")
        self.assertEqual(result.input_tokens, 42)
        self.assertGreaterEqual(result.latency_ms, 0)
        self.assertEqual(result.answers["runtime_call"], JevAnswer(kind="noul", noul=0.91))
        self.assertEqual(
            result.answers["target"],
            JevAnswer(kind="choice", choice="A", confidence=0.7,
                      probabilities={"A": 0.7, "B": 0.2, "none": 0.1}),
        )
        # Score probabilities arrive int-keyed from the SDK; we log/replay JSON, so str.
        self.assertEqual(
            result.answers["strength"],
            JevAnswer(kind="score", score=1.5, confidence=0.55,
                      probabilities={"0": 0.1, "1": 0.3, "2": 0.6}),
        )

    def test_to_log_round_trips(self):
        result = client_returning(always(200, ANSWERS_BODY)).ask("s", QUESTIONS)
        log = json.loads(json.dumps(result.to_log()))
        self.assertEqual(log["model"], "jev-1.13.0")
        self.assertEqual(log["answers"]["target"]["choice"], "A")
        self.assertEqual(JevResult.from_log(log), result)

    def test_usage_counts_calls_tokens_and_failures(self):
        calls = iter([200, 500, 200])

        def handler(request):
            status = next(calls)
            return httpx2.Response(status, json=ANSWERS_BODY if status == 200 else {"error": "x"})

        client = client_returning(handler)
        client.ask("a", QUESTIONS)
        with self.assertRaises(JevError):
            client.ask("b", QUESTIONS)
        client.ask("c", QUESTIONS)
        self.assertEqual(client.usage, {"calls": 3, "input_tokens": 84, "failures": 1})

    def test_401_becomes_jev_error_with_cause(self):
        with self.assertRaises(JevError) as ctx:
            client_returning(always(401, {"error": "bad key"})).ask("s", QUESTIONS)
        self.assertIsInstance(ctx.exception.cause, TypeSafeAuthenticationError)
        self.assertIn("401", str(ctx.exception))

    def test_500_becomes_jev_error_after_retries(self):
        attempts = []

        def handler(request):
            attempts.append(1)
            return httpx2.Response(500, json={"error": "boom"})

        client = JevClient(
            api_key="k", model="m", transport=httpx2.MockTransport(handler),
            retry=RetryPolicy(max_retries=1, backoff_initial=0, backoff_max=0),
        )
        with self.assertRaises(JevError) as ctx:
            client.ask("s", QUESTIONS)
        self.assertIsInstance(ctx.exception.cause, TypeSafeInternalServerError)
        self.assertEqual(len(attempts), 2)  # the SDK retried once, then we wrapped

    def test_ask_many_isolates_one_failure(self):
        def handler(request):
            if json.loads(request.content)["state"] == "bad":
                return httpx2.Response(500, json={"error": "boom"})
            return httpx2.Response(200, json=ANSWERS_BODY)

        client = client_returning(handler)
        out = client.ask_many(
            [("k1", "good", QUESTIONS), ("k2", "bad", QUESTIONS), ("k3", "good", QUESTIONS)],
            workers=3,
        )
        self.assertEqual(set(out), {"k1", "k2", "k3"})
        self.assertIsInstance(out["k1"], JevResult)
        self.assertIsInstance(out["k2"], JevError)
        self.assertIsInstance(out["k3"], JevResult)
        self.assertEqual(client.usage, {"calls": 3, "input_tokens": 84, "failures": 1})

    def test_ask_many_with_nothing_to_ask(self):
        self.assertEqual(client_returning(always(200, ANSWERS_BODY)).ask_many([]), {})


class EnabledTests(SimpleTestCase):
    ON = {"JEV_ENABLED": True, "TYPESAFE_API_KEY": "k", "AIRGAPPED": False}

    def test_enabled_needs_flag_and_key_and_not_airgapped(self):
        cases = {
            "all good": (dict(self.ON), True),
            "flag off": (dict(self.ON, JEV_ENABLED=False), False),
            "no key": (dict(self.ON, TYPESAFE_API_KEY=""), False),
            "airgapped wins": (dict(self.ON, AIRGAPPED=True), False),
        }
        for name, (overrides, expected) in cases.items():
            with self.subTest(name), override_settings(**overrides):
                self.assertIs(jev_enabled(), expected)

    def test_from_settings_is_none_when_disabled(self):
        with override_settings(**dict(self.ON, JEV_ENABLED=False)):
            self.assertIsNone(JevClient.from_settings())
        with override_settings(**dict(self.ON, AIRGAPPED=True)):
            self.assertIsNone(JevClient.from_settings())

    def test_from_settings_builds_a_client_when_enabled(self):
        with override_settings(**self.ON, JEV_MODEL="jev-9.9.9", JEV_TIMEOUT=7.0):
            client = JevClient.from_settings()
        self.assertIsInstance(client, JevClient)
        self.assertEqual(client.model, "jev-9.9.9")
        self.assertEqual(client.usage, {"calls": 0, "input_tokens": 0, "failures": 0})


class CassetteTests(TmpPathMixin, SimpleTestCase):
    def test_key_is_deterministic_and_ignores_dict_order(self):
        a = cassette_key({"x": 1, "y": 2}, QUESTIONS)
        b = cassette_key({"y": 2, "x": 1}, dict(reversed(list(QUESTIONS.items()))))
        self.assertEqual(a, b)
        self.assertEqual(len(a), 64)
        self.assertNotEqual(a, cassette_key({"x": 1, "y": 3}, QUESTIONS))
        # a question dict in wire form hashes like the SDK object it came from
        plain = {k: q.model_dump() for k, q in QUESTIONS.items()}
        self.assertEqual(a, cassette_key({"x": 1, "y": 2}, plain))

    def test_recording_writes_cassette_and_replay_returns_the_same_results(self):
        path = self.tmp_path / "jev" / "cassette.json"
        inner = client_returning(always(200, ANSWERS_BODY))
        recorder = RecordingJevClient(inner, path)

        live = recorder.ask_many([("k1", {"n": 1}, QUESTIONS), ("k2", {"n": 2}, QUESTIONS)])
        self.assertIs(recorder.usage, inner.usage)
        self.assertEqual(recorder.usage["calls"], 2)

        entries = json.loads(path.read_text())
        self.assertEqual(set(entries), {cassette_key({"n": 1}, QUESTIONS), cassette_key({"n": 2}, QUESTIONS)})
        entry = entries[cassette_key({"n": 1}, QUESTIONS)]
        self.assertEqual(entry["state"], {"n": 1})
        self.assertEqual(entry["questions"]["target"]["criteria"], {"A": None, "B": None, "none": None})
        self.assertEqual(entry["result"]["answers"]["target"]["choice"], "A")

        replay = ReplayJevClient(path)
        again = replay.ask_many([("k1", {"n": 1}, QUESTIONS), ("k2", {"n": 2}, QUESTIONS)])
        self.assertEqual(again, live)
        self.assertEqual(replay.usage, {"calls": 2, "input_tokens": 84, "failures": 0})

    def test_recording_extends_an_existing_cassette(self):
        path = self.tmp_path / "cassette.json"
        RecordingJevClient(client_returning(always(200, ANSWERS_BODY)), path).ask({"n": 1}, QUESTIONS)
        RecordingJevClient(client_returning(always(200, ANSWERS_BODY)), path).ask({"n": 2}, QUESTIONS)
        self.assertEqual(len(json.loads(path.read_text())), 2)

    def test_recording_does_not_record_failures(self):
        path = self.tmp_path / "cassette.json"
        recorder = RecordingJevClient(client_returning(always(500, {"error": "x"})), path)
        with self.assertRaises(JevError):
            recorder.ask({"n": 1}, QUESTIONS)
        self.assertFalse(path.exists())

    def test_replay_unknown_state_raises_jev_error(self):
        path = self.tmp_path / "cassette.json"
        RecordingJevClient(client_returning(always(200, ANSWERS_BODY)), path).ask({"n": 1}, QUESTIONS)
        replay = ReplayJevClient(path)
        with self.assertRaises(JevError) as ctx:
            replay.ask({"n": "never seen"}, QUESTIONS)
        self.assertIsInstance(ctx.exception, JevReplayMiss)
        self.assertIsInstance(ctx.exception, KeyError)
        out = replay.ask_many([("k", {"n": "never seen"}, QUESTIONS)])
        self.assertIsInstance(out["k"], JevError)
        self.assertEqual(replay.usage["failures"], 2)


class FakeJevClientTests(SimpleTestCase):
    def test_records_calls_and_answers_from_a_dict(self):
        answers = {"target": JevAnswer(kind="choice", choice="A", confidence=0.9, probabilities={"A": 0.9})}
        fake = FakeJevClient(answers)
        result = fake.ask({"n": 1}, QUESTIONS)
        self.assertEqual(result.answers, answers)
        self.assertEqual(result.model, "fake-jev")
        self.assertEqual(fake.calls, [({"n": 1}, QUESTIONS)])
        self.assertEqual(fake.usage["calls"], 1)

    def test_answers_from_a_function_see_the_state(self):
        fake = FakeJevClient(lambda state, questions: {"n": JevAnswer(kind="noul", noul=state["p"])})
        out = fake.ask_many([("a", {"p": 0.2}, QUESTIONS), ("b", {"p": 0.8}, QUESTIONS)])
        self.assertEqual(out["a"].answers["n"].noul, 0.2)
        self.assertEqual(out["b"].answers["n"].noul, 0.8)
        self.assertEqual(len(fake.calls), 2)

    def test_raise_on_fails_every_ask_but_ask_many_still_returns(self):
        fake = FakeJevClient(raise_on=JevError("down"))
        with self.assertRaises(JevError):
            fake.ask("s", QUESTIONS)
        out = fake.ask_many([("k", "s", QUESTIONS)])
        self.assertIsInstance(out["k"], JevError)
        self.assertEqual(fake.usage["failures"], 2)
