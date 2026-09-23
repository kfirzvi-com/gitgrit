"""Best-effort discovery of the models an LLM provider supports.

Runs host-side (never in the sandbox). Uses stdlib ``urllib`` so it adds no
new dependency — same approach as the sandbox git providers. Returns a list of
bare model-name strings; an empty list means discovery isn't supported or
failed, and the UI falls back to manual entry.

Two steps: fetch the provider's catalog, then keep only the models *this key*
can call. No provider's list endpoint reflects entitlements — a free-tier
Gemini key lists every Gemini model, an Anthropic key with no credit lists
every Claude — so each candidate gets one tiny ``litellm.completion`` probe
(the exact call the agent makes). A model is dropped only on a definite
rejection (400/401/403/404, or a 429 whose quota limit is 0); timeouts,
5xx and other unknowns keep the model so a flaky network never hides one.

Why not LiteLLM's ``get_valid_models``? The pinned 1.88.1 can only list live
for Anthropic/OpenAI/Gemini (Bedrock returns [], Vertex raises), and its
module-level HTTP client has a 6000s timeout we can't override per call.
Doing the three request shapes here keeps a hard 10s budget on the request
thread.
"""
from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

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

# HTTP statuses that mean "this key can't use this model": bad model, bad key,
# no credit (Gemini 402 "prepayment credits are depleted", Anthropic 400
# "credit balance is too low"), no permission, retired model (Gemini 404
# "no longer available to new users").
_REJECT_STATUSES = frozenset({400, 401, 402, 403, 404})

# The provider's own status inside the error body, e.g. Gemini's
# {"error": {"code": 402, ...}}. LiteLLM has no exception class for some codes
# and files them as APIConnectionError with status_code 500, so the body's
# code is the trustworthy one when present.
_BODY_CODE = re.compile(r'"code"\s*:\s*([1-5]\d\d)\b')

# Gemini reports a model outside the key's tier as a 429 whose quota limit is
# literally 0 — distinct from a real rate limit, which has a non-zero limit.
_ZERO_QUOTA = re.compile(r'"quotaValue"\s*:\s*"0"|\blimit:\s*0\b')

PROBE_TIMEOUT = 8.0  # seconds per model
PROBE_BUDGET = 20.0  # seconds for the whole batch; Kamal proxy cuts at 30s
PROBE_WORKERS = 8


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


def fetch_catalog(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> list[str]:
    """The provider's full model list, unfiltered. Raises on failure."""
    url, style = _models_endpoint(provider_type, base_url)
    if not url:
        return []
    req = urllib.request.Request(url, headers=_headers(style, api_key))
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    return _parse_models(style, data)


@dataclass(frozen=True)
class ProbeResult:
    """Outcome of one access probe. ``verdict``: True usable, False rejected,
    None unknown (kept). ``detail`` is the provider's error text, whitespace
    collapsed and truncated, for logs and the ``probe_llm_models`` command."""

    model: str
    verdict: bool | None
    status: int | None = None
    detail: str = ""

    @property
    def label(self) -> str:
        return {True: "usable", False: "rejected", None: "unknown"}[self.verdict]


def _probe_model(
    provider_type: str, base_url: str, api_key: str, model: str, timeout: float
) -> ProbeResult:
    import litellm  # heavy import; already loaded by llm_agent in the app process

    litellm.suppress_debug_info = True  # no "Give Feedback / Get Help" banner per failure
    try:
        litellm.completion(
            model=f"{provider_type}/{model}",
            messages=[{"role": "user", "content": "hi"}],
            max_tokens=1,
            api_key=api_key or None,
            api_base=base_url or None,
            timeout=timeout,
        )
        return ProbeResult(model, True, 200)
    except Exception as exc:  # noqa: BLE001 — classify by status, never raise
        text = str(exc)
        body_code = _BODY_CODE.search(text)
        status = int(body_code.group(1)) if body_code else getattr(exc, "status_code", None)
        detail = f"{type(exc).__name__}: " + " ".join(text.split())[:400]
        if status == 429:
            verdict: bool | None = not _ZERO_QUOTA.search(text)
        elif status in _REJECT_STATUSES:
            verdict = False
        else:
            verdict = None
        return ProbeResult(model, verdict, status, detail)


def probe_models(
    provider_type: str,
    base_url: str,
    api_key: str,
    models: list[str],
    *,
    timeout: float = PROBE_TIMEOUT,
    budget: float = PROBE_BUDGET,
) -> list[ProbeResult]:
    """Probe every model in parallel; results in catalog order.

    Runs under a wall-clock ``budget``. Anything still unanswered at the
    deadline comes back as unknown (kept), never rejected.
    """
    if not models:
        return []
    results: dict[str, ProbeResult] = {}
    pool = ThreadPoolExecutor(max_workers=PROBE_WORKERS)
    futures = {
        pool.submit(_probe_model, provider_type, base_url, api_key, m, timeout): m
        for m in models
    }
    started = time.monotonic()
    try:
        for fut in as_completed(futures, timeout=budget):
            results[futures[fut]] = fut.result()
    except TimeoutError:
        logger.warning(
            "LLM model probe for %s hit the %.0fs budget; keeping %d unprobed",
            provider_type, budget, len(models) - len(results),
        )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    ordered = [
        results.get(m, ProbeResult(m, None, None, f"no answer within {budget:.0f}s budget"))
        for m in models
    ]
    for r in ordered:
        logger.info(
            "LLM model probe %s/%s: %s (%s) %s",
            provider_type, r.model, r.label, r.status, r.detail[:200],
        )
    logger.info(
        "LLM model probe for %s: %d/%d usable in %.1fs",
        provider_type, sum(1 for r in ordered if r.verdict is not False), len(models),
        time.monotonic() - started,
    )
    return ordered


def _usable_models(
    provider_type: str,
    base_url: str,
    api_key: str,
    models: list[str],
    *,
    timeout: float = PROBE_TIMEOUT,
    budget: float = PROBE_BUDGET,
) -> list[str]:
    """Filter ``models`` to those the key can call; keeps catalog order."""
    results = probe_models(provider_type, base_url, api_key, models, timeout=timeout, budget=budget)
    return [r.model for r in results if r.verdict is not False]


_BODY_MESSAGE = re.compile(r'"message"\s*:\s*"((?:[^"\\]|\\.)*)"')


@dataclass(frozen=True)
class Discovery:
    """What discovery found: the usable models plus, when nothing is usable,
    the provider's own explanation (e.g. "Your prepayment credits are
    depleted") so the UI can say *why* instead of just "none"."""

    models: list[str]
    results: list[ProbeResult]

    @property
    def reason(self) -> str:
        if self.models or not self.results:
            return ""
        rejected = [r for r in self.results if r.verdict is False]
        if not rejected:
            return ""
        # The most common rejection text is the story for this key.
        counts: dict[str, int] = {}
        for r in rejected:
            m = _BODY_MESSAGE.search(r.detail)
            key = m.group(1) if m else r.detail
            counts[key] = counts.get(key, 0) + 1
        text = max(counts, key=counts.get)
        text = text.split(". ")[0].rstrip(".")  # first sentence is enough
        return text[:140]


def discover(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> Discovery:
    """Catalog → probe → the models this key can use. Empty on any failure."""
    try:
        catalog = fetch_catalog(provider_type, base_url, api_key, timeout)
    except Exception as exc:  # noqa: BLE001 — best-effort; caller falls back
        logger.warning("LLM model discovery failed for %s: %s", provider_type, exc)
        return Discovery([], [])
    results = probe_models(provider_type, base_url, api_key, catalog)
    return Discovery([r.model for r in results if r.verdict is not False], results)


def discover_models(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> list[str]:
    """Return the model IDs this key can use, or [] on failure (manual fallback)."""
    return discover(provider_type, base_url, api_key, timeout).models


def test_provider(
    provider_type: str, base_url: str, api_key: str, timeout: float = 10.0
) -> bool:
    """True when the provider's models endpoint accepts the credentials."""
    try:
        fetch_catalog(provider_type, base_url, api_key, timeout)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.info("LLM provider test failed for %s: %s", provider_type, exc)
        return False
