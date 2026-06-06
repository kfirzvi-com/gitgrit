"""Best-effort discovery of the models an LLM provider supports.

Runs host-side (never in the sandbox). Uses stdlib ``urllib`` so it adds no
new dependency — same approach as the sandbox git providers. Returns a list of
bare model-name strings; an empty list means discovery isn't supported or
failed, and the UI falls back to manual entry.
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
}


def _models_endpoint(provider_type: str, base_url: str) -> tuple[str | None, str]:
    base = (base_url or "").rstrip("/") or _DEFAULT_BASE.get(provider_type, "")
    if not base:
        return None, "openai"
    if provider_type == LLMProviderType.ANTHROPIC:
        return f"{base}/v1/models", "anthropic"
    # Everything else (openai, azure, mistral, ollama, litellm_proxy, …) speaks
    # the OpenAI-compatible GET /models shape.
    return f"{base}/models", "openai"


def _fetch_models(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> list[str]:
    url, style = _models_endpoint(provider_type, base_url)
    if not url:
        return []
    headers = {"Accept": "application/json"}
    if style == "anthropic":
        headers["x-api-key"] = api_key or ""
        headers["anthropic-version"] = "2023-06-01"
    elif api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())

    items = data.get("data", []) if isinstance(data, dict) else []
    return [m["id"] for m in items if isinstance(m, dict) and m.get("id")]


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
