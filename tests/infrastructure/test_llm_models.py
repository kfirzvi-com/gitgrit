"""Model discovery: per-provider request shape and response parsing."""
import io
import json
from unittest.mock import patch

from app.infrastructure.llm_models import discover_models
from app.infrastructure.llm_models import test_provider as check_provider

URLOPEN = "app.infrastructure.llm_models.urllib.request.urlopen"


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(payload):
    """Patch urlopen; return (patcher, requests) so tests can inspect the call."""
    sent = []

    def fake(req, timeout):
        sent.append(req)
        return _Resp(json.dumps(payload).encode())

    return patch(URLOPEN, side_effect=fake), sent


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
