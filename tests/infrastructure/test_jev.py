"""The Jev client maps SDK answers to plain results, counts usage, and keeps
one bad call from sinking a batch. No network: the SDK's HTTP layer is
``httpx2`` (a vendored httpx fork), so its ``MockTransport`` stands in for
api.typesafe.ai. Retries are turned off so the 5xx test does not sleep.

``SimpleTestCase`` because CI runs ``manage.py test`` and its loader only
sees TestCase subclasses; ``for_tenant`` reads provider rows, so its tests
are a ``TestCase``.
"""
from __future__ import annotations

import json

import httpx2
from django.test import SimpleTestCase, TestCase, override_settings
from model_bakery import baker
from typesafe_sdk import (
    Choice,
    Noul,
    RetryPolicy,
    Score,
    TypeSafeClient,
    TypeSafeAuthenticationError,
    TypeSafeError,
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
from tests.support import MonkeyPatchMixin, TmpPathMixin

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


PING_BODY = {
    "model": "jev-1.13.0",
    "usage": {"input_tokens": 3, "output_tokens": 1},
    "answers": {"ok": {"type": "noul", "noul": 0.9}},
}


class PingTests(SimpleTestCase):
    def test_ping_asks_one_noul_question(self):
        sent = {}

        def handler(request):
            sent["body"] = json.loads(request.content)
            return httpx2.Response(200, json=PING_BODY)

        client = client_returning(handler)
        self.assertIsNone(client.ping())
        self.assertEqual(list(sent["body"]["questions"]), ["ok"])
        self.assertEqual(sent["body"]["questions"]["ok"]["type"], "noul")
        self.assertEqual(client.usage["calls"], 1)

    def test_ping_raises_jev_error_on_sdk_error(self):
        with self.assertRaises(JevError) as ctx:
            client_returning(always(401, {"error": "bad key"})).ping()
        self.assertIsInstance(ctx.exception.cause, TypeSafeAuthenticationError)

    def test_malformed_key_is_a_jev_error_at_construction(self):
        with self.assertRaises(JevError) as ctx:
            JevClient(api_key="bad key", model="m")
        self.assertIsInstance(ctx.exception.cause, TypeSafeError)
        self.assertIn("printable ASCII", str(ctx.exception))

    def test_close_closes_the_sdk_client(self):
        client = client_returning(always(200, PING_BODY))
        client.close()
        with self.assertRaises(RuntimeError):  # httpx: client has been closed
            client.ping()


class _CaptureSDK:
    """Stands in for ``TypeSafeClient`` so a test can read what a client was
    built with (the key is not exposed by the real SDK)."""

    built: list[dict] = []

    def __init__(self, **kwargs):
        _CaptureSDK.built.append(kwargs)


class ForTenantTests(MonkeyPatchMixin, TestCase):
    OFF = {"JEV_ENABLED": False, "TYPESAFE_API_KEY": "", "AIRGAPPED": False}

    def setUp(self):
        super().setUp()
        _CaptureSDK.built = []
        self.monkeypatch.setattr("app.infrastructure.jev.TypeSafeClient", _CaptureSDK)
        self.tenant = baker.make("app.Tenant")

    def _typesafe(self, **kw):
        defaults = dict(
            tenant=self.tenant,
            provider_type="typesafe",
            display_name="TypeSafe (Jev)",
            api_key="ts-key",
            base_url="",
            available_models=["jev-2.0.0"],
            enabled=True,
        )
        defaults.update(kw)
        return baker.make("app.LLMProvider", **defaults)

    def test_enabled_provider_gives_a_client_with_its_key_and_model(self):
        self._typesafe(base_url="https://jev.example.test")
        with override_settings(**self.OFF, JEV_TIMEOUT=7.0):
            client = JevClient.for_tenant(self.tenant)
        self.assertIsInstance(client, JevClient)
        self.assertEqual(client.model, "jev-2.0.0")
        built = _CaptureSDK.built[-1]
        self.assertEqual(built["api_key"], "ts-key")  # decrypted from the row
        self.assertEqual(built["base_url"], "https://jev.example.test")
        self.assertEqual(built["timeout"], 7.0)

    def test_provider_without_models_uses_the_settings_model(self):
        self._typesafe(available_models=[])
        with override_settings(**self.OFF, JEV_MODEL="jev-9.9.9"):
            client = JevClient.for_tenant(self.tenant)
        self.assertEqual(client.model, "jev-9.9.9")
        self.assertIsNone(_CaptureSDK.built[-1]["base_url"])

    def test_disabled_provider_falls_back_to_the_env_path(self):
        self._typesafe(enabled=False)
        with override_settings(**self.OFF):
            self.assertIsNone(JevClient.for_tenant(self.tenant))
        with override_settings(JEV_ENABLED=True, TYPESAFE_API_KEY="env-key", AIRGAPPED=False):
            client = JevClient.for_tenant(self.tenant)
        self.assertIsInstance(client, JevClient)
        self.assertEqual(_CaptureSDK.built[-1]["api_key"], "env-key")

    def test_another_workspaces_provider_does_not_count(self):
        self._typesafe(tenant=baker.make("app.Tenant"))
        with override_settings(**self.OFF):
            self.assertIsNone(JevClient.for_tenant(self.tenant))

    def test_for_provider_is_the_builder_the_map_and_the_test_button_share(self):
        provider = self._typesafe(base_url="https://jev.example.test")
        retry = RetryPolicy(max_retries=0)
        client = JevClient.for_provider(provider, timeout=3.0, retry=retry)
        self.assertEqual(client.model, "jev-2.0.0")
        built = _CaptureSDK.built[-1]
        self.assertEqual(
            (built["api_key"], built["base_url"], built["timeout"]),
            ("ts-key", "https://jev.example.test", 3.0),
        )
        self.assertIs(built["retry"], retry)

    def test_malformed_row_logs_and_turns_jev_off(self):
        # The real SDK rejects the key before any network call.
        self.monkeypatch.setattr("app.infrastructure.jev.TypeSafeClient", TypeSafeClient)
        self._typesafe(api_key="bad key")
        with override_settings(**self.OFF), self.assertLogs("app.infrastructure.jev", "WARNING") as logs:
            self.assertIsNone(JevClient.for_tenant(self.tenant))
        self.assertIn("unusable", logs.output[0])
        self.assertNotIn("bad key", logs.output[0])

    def test_airgapped_wins_even_with_a_provider(self):
        self._typesafe()
        with override_settings(JEV_ENABLED=True, TYPESAFE_API_KEY="k", AIRGAPPED=True):
            self.assertIsNone(JevClient.for_tenant(self.tenant))
        self.assertEqual(_CaptureSDK.built, [])


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
