"""Model discovery: per-provider request shape, response parsing, access probe."""
import io
import json
from unittest.mock import patch

import pytest

from app.infrastructure.llm_models import _probe_model, _usable_models, discover_models
from app.infrastructure.llm_models import test_provider as check_provider

URLOPEN = "app.infrastructure.llm_models.urllib.request.urlopen"
PROBE = "app.infrastructure.llm_models._probe_model"
COMPLETION = "litellm.completion"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _Patchers:
    def __init__(self, *patchers):
        self._patchers = patchers

    def __enter__(self):
        for p in self._patchers:
            p.start()
        return self

    def __exit__(self, *a):
        for p in self._patchers:
            p.stop()
        return False


def _capture(payload):
    """Patch urlopen (and accept every probe); return (patcher, requests)."""
    sent = []

    def fake(req, timeout):
        sent.append(req)
        return _Resp(json.dumps(payload).encode())

    return _Patchers(patch(URLOPEN, side_effect=fake), patch(PROBE, return_value=True)), sent


def test_gemini_uses_default_root_key_header_and_filters_chat_models():
    payload = {
        "models": [
            {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/gemini-legacy"},  # no methods field → keep
        ]
    }
    patcher, sent = _capture(payload)
    with patcher:
        models = discover_models("gemini", "", "g-key")

    assert models == ["gemini-2.5-pro", "gemini-legacy"]
    req = sent[0]
    assert req.full_url == "https://generativelanguage.googleapis.com/v1beta/models"
    assert req.get_header("X-goog-api-key") == "g-key"
    assert req.get_header("Authorization") is None


def test_gemini_honours_custom_base_url():
    patcher, sent = _capture({"models": []})
    with patcher:
        discover_models("gemini", "https://proxy.example/v1beta/", "k")
    assert sent[0].full_url == "https://proxy.example/v1beta/models"


def test_anthropic_shape_unchanged():
    patcher, sent = _capture({"data": [{"id": "claude-opus-5"}]})
    with patcher:
        assert discover_models("anthropic", "", "a-key") == ["claude-opus-5"]
    req = sent[0]
    assert req.full_url == "https://api.anthropic.com/v1/models"
    assert req.get_header("X-api-key") == "a-key"


def test_openai_compatible_shape_unchanged():
    patcher, sent = _capture({"data": [{"id": "gpt-5"}]})
    with patcher:
        assert discover_models("mistral", "", "m-key") == ["gpt-5"]
    assert sent[0].full_url == "https://api.mistral.ai/v1/models"
    assert sent[0].get_header("Authorization") == "Bearer m-key"


def test_bedrock_and_vertex_skip_network():
    with patch(URLOPEN) as urlopen:
        assert discover_models("bedrock", "", "k") == []
        assert discover_models("vertex_ai", "", "k") == []
        assert check_provider("bedrock", "", "k") is True  # nothing to reject
    urlopen.assert_not_called()


def test_network_failure_falls_back_to_empty():
    with patch(URLOPEN, side_effect=OSError("boom")):
        assert discover_models("gemini", "", "k") == []
        assert check_provider("gemini", "", "k") is False


# --- access probe -----------------------------------------------------------


def test_discovery_drops_models_the_key_is_denied():
    payload = {"data": [{"id": "gpt-5"}, {"id": "o3-pro"}, {"id": "gpt-4o"}]}
    sent = []

    def fake_open(req, timeout):
        sent.append(req)
        return _Resp(json.dumps(payload).encode())

    verdict = {"gpt-5": True, "o3-pro": False, "gpt-4o": None}
    with patch(URLOPEN, side_effect=fake_open), patch(
        PROBE, side_effect=lambda pt, b, k, m, t: verdict[m]
    ):
        assert discover_models("openai", "", "k") == ["gpt-5", "gpt-4o"]  # unknown kept


def test_usable_models_keeps_catalog_order_and_skips_empty():
    with patch(PROBE, side_effect=lambda pt, b, k, m, t: m != "b") as probe:
        assert _usable_models("gemini", "", "k", ["a", "b", "c"]) == ["a", "c"]
        assert probe.call_count == 3
        assert _usable_models("gemini", "", "k", []) == []
    probe.assert_any_call("gemini", "", "k", "c", 8.0)


def test_usable_models_keeps_models_still_pending_at_deadline():
    import threading

    release = threading.Event()

    def slow(pt, b, k, m, t):
        if m == "slow":
            release.wait(2)
            return False
        return True

    with patch(PROBE, side_effect=slow):
        result = _usable_models("gemini", "", "k", ["fast", "slow"], budget=0.2)
    release.set()
    assert result == ["fast", "slow"]


class _Forbidden(Exception):
    """Stand-in for litellm.PermissionDeniedError, whose ctor needs a raw response."""

    status_code = 403


def _exc(cls, message="x"):
    if cls is _Forbidden:
        return cls(message)
    return cls(message=message, llm_provider="gemini", model="gemini/m")


@pytest.mark.parametrize(
    ("side_effect", "expected"),
    [
        (None, True),
        ("AuthenticationError", False),
        (_Forbidden, False),
        ("NotFoundError", False),
        ("BadRequestError", False),  # e.g. Anthropic "credit balance is too low"
        ("APIConnectionError", None),  # 500-class → unknown, keep
        ("Timeout", None),
    ],
)
def test_probe_classifies_litellm_errors(side_effect, expected):
    import litellm.exceptions as ex

    effect = None
    if side_effect:
        cls = side_effect if isinstance(side_effect, type) else getattr(ex, side_effect)
        effect = _exc(cls)
    with patch(COMPLETION, side_effect=effect) as completion:
        assert _probe_model("gemini", "", "g-key", "gemini-2.5-flash", 8.0) is expected
    kwargs = completion.call_args.kwargs
    assert kwargs["model"] == "gemini/gemini-2.5-flash"
    assert kwargs["api_key"] == "g-key"
    assert kwargs["api_base"] is None
    assert kwargs["max_tokens"] == 1
    assert kwargs["timeout"] == 8.0


def test_probe_treats_zero_quota_429_as_no_access_but_real_rate_limit_as_access():
    import litellm.exceptions as ex

    gated = (
        'geminiException - {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", '
        '"details": [{"violations": [{"quotaMetric": '
        '"generativelanguage.googleapis.com/generate_content_free_tier_requests", '
        '"quotaDimensions": {"model": "gemini-2.5-pro"}, "quotaValue": "0"}]}]}}'
    )
    busy = gated.replace('"quotaValue": "0"', '"quotaValue": "10"')
    with patch(COMPLETION, side_effect=_exc(ex.RateLimitError, gated)):
        assert _probe_model("gemini", "", "k", "gemini-2.5-pro", 8.0) is False
    with patch(COMPLETION, side_effect=_exc(ex.RateLimitError, busy)):
        assert _probe_model("gemini", "", "k", "gemini-2.5-flash", 8.0) is True


def test_probe_passes_custom_base_url():
    with patch(COMPLETION) as completion:
        assert _probe_model("litellm_proxy", "https://llm.example/v1", "k", "qwen", 8.0) is True
    assert completion.call_args.kwargs["api_base"] == "https://llm.example/v1"
