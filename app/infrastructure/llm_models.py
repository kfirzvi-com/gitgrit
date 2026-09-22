"""Best-effort discovery of the models an LLM provider supports.

Runs host-side (never in the sandbox). Uses stdlib ``urllib`` so it adds no
new dependency — same approach as the sandbox git providers. Returns a list of
bare model-name strings; an empty list means discovery isn't supported or
failed, and the UI falls back to manual entry.

Why not LiteLLM's ``get_valid_models``? The pinned 1.88.1 can only list live
for Anthropic/OpenAI/Gemini (Bedrock returns [], Vertex raises), and its
module-level HTTP client has a 6000s timeout we can't override per call.
Doing the three request shapes here keeps a hard 10s budget on the request
thread.
"""
from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request

from app.domain.models import LLMProviderType

logger = logging.getLogger(__name__)

# Default API roots for hosted providers that don't need a custom base_url.
_DEFAULT_BASE = {
    LLMProviderType.ANTHROPIC: "https://api.anthropic.com",
    LLMProviderType.OPENAI: "https://api.openai.com/v1",
    LLMProviderType.MISTRAL: "https://api.mistral.ai/v1",
    LLMProviderType.GEMINI: "https://generativelanguage.googleapis.com/v1beta",
}

# Providers whose model catalog can't be listed with a bare API key
# (Bedrock needs SigV4 + region, Vertex needs GCP OAuth + project). Skip the
# network round-trip and go straight to manual entry.
_NO_DISCOVERY = frozenset({LLMProviderType.BEDROCK, LLMProviderType.VERTEX_AI})


def _models_endpoint(provider_type: str, base_url: str) -> tuple[str | None, str]:
    if provider_type in _NO_DISCOVERY:
        return None, "none"
    base = (base_url or "").rstrip("/") or _DEFAULT_BASE.get(provider_type, "")
    if not base:
        return None, "openai"
    if provider_type == LLMProviderType.ANTHROPIC:
        return f"{base}/v1/models", "anthropic"
    if provider_type == LLMProviderType.GEMINI:
        return f"{base}/models", "gemini"
    # Everything else (openai, azure, mistral, ollama, litellm_proxy, …) speaks
    # the OpenAI-compatible GET /models shape.
    return f"{base}/models", "openai"


def _headers(style: str, api_key: str) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if style == "anthropic":
        headers["x-api-key"] = api_key or ""
        headers["anthropic-version"] = "2023-06-01"
    elif style == "gemini":
        headers["x-goog-api-key"] = api_key or ""
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _parse_models(style: str, data: object) -> list[str]:
    if not isinstance(data, dict):
        return []
    if style == "gemini":
        # {"models": [{"name": "models/gemini-2.5-pro",
        #              "supportedGenerationMethods": ["generateContent", …]}]}
        # Keep only chat-capable models; embeddings/imagen can't run an agent.
        names = []
        for m in data.get("models", []):
            if not isinstance(m, dict) or not m.get("name"):
                continue
            methods = m.get("supportedGenerationMethods")
            if methods is not None and "generateContent" not in methods:
                continue
            names.append(m["name"].removeprefix("models/"))
        return names
    # Anthropic and OpenAI-compatible: {"data": [{"id": "..."}]}
    return [m["id"] for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]


def _fetch_models(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> list[str]:
    url, style = _models_endpoint(provider_type, base_url)
    if not url:
        return []
    req = urllib.request.Request(url, headers=_headers(style, api_key))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return _parse_models(style, data)


def discover_models(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> list[str]:
    """Return the provider's model IDs, or [] on any failure (manual fallback)."""
    try:
        return _fetch_models(provider_type, base_url, api_key, timeout)
    except Exception as exc:  # noqa: BLE001 — best-effort; caller falls back
        logger.warning("LLM model discovery failed for %s: %s", provider_type, exc)
        return []


def test_provider(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> bool:
    """True when the provider's models endpoint accepts the credentials."""
    try:
        _fetch_models(provider_type, base_url, api_key, timeout)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM provider test failed for %s: %s", provider_type, exc)
        return False
