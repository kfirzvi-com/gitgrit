"""Keep credentials out of logs and stored results.

The input a sandbox run gets (/input.json) carries the repository access
token and the workspace's LLM API keys, and the LLM provider calls (model
discovery, the dependency map) hold a key too. A standard's code, a library
error or Docker can echo them, so what we log, store or publish from those
paths goes through ``redact`` with the secrets in play.

This covers accidental echoes: an echoed secret is replaced with
``[redacted]``, and so is its first ``PREFIX_LENGTH`` characters (for
secrets of ``MIN_PREFIX_SECRET_LENGTH`` or more), so an error message that
truncates a key is still caught. It is not a defence against deliberate
exfiltration: code that sees a secret can always encode or split it.
"""
import re
import traceback

from app.domain.limits import MAX_ERROR_TEXT

REDACTED = "[redacted]"
# Shorter values are not credentials and would blank out ordinary words.
MIN_SECRET_LENGTH = 8
# A long prefix of a long secret is still enough to be worth hiding. It can
# also cover a vendor's public prefix ("sk-ant-api03"); hiding that is harmless.
PREFIX_LENGTH = 12
MIN_PREFIX_SECRET_LENGTH = 16


def secrets_of(*tokens, llm_roles=None) -> set[str]:
    """The credentials among platform tokens and LLM roles (as
    ``resolve_llm_roles`` returns them): each token and every role's API key.
    Empty and short values are left out."""
    found = list(tokens)
    for role in (llm_roles or {}).values():
        found.append((role or {}).get("api_key"))
    return {s for s in found if isinstance(s, str) and len(s) >= MIN_SECRET_LENGTH}


def secrets_in(input_config: dict) -> set[str]:
    """The credentials in a run's input: the platform access token and every
    LLM role's API key."""
    return secrets_of(
        input_config.get("access_token"), llm_roles=input_config.get("llm_roles")
    )


def redacted_failure(exc: BaseException, secrets) -> tuple[str, str]:
    """``(message, stack)`` for an exception being handled: its text cut to
    ``MAX_ERROR_TEXT`` for storing, and the formatted traceback for the log,
    both redacted. Log the stack as text rather than with ``exc_info``, which
    would print the raw message."""
    message = redact(str(exc), secrets)[:MAX_ERROR_TEXT]
    stack = redact("".join(traceback.format_exception(exc)), secrets)
    return message, stack


def redact(value, secrets):
    """``value`` with every secret (and a long prefix of it) replaced, through
    nested dicts (keys too) and lists. Empty or short secrets are ignored."""
    pattern = _pattern(secrets)
    if pattern is None:
        return value
    return _redact(value, pattern)


def _pattern(secrets) -> re.Pattern | None:
    needles = set()
    for secret in secrets or ():
        if not isinstance(secret, str) or len(secret) < MIN_SECRET_LENGTH:
            continue
        needles.add(secret)
        if len(secret) >= MIN_PREFIX_SECRET_LENGTH:
            needles.add(secret[:PREFIX_LENGTH])
    if not needles:
        return None
    # Longest first, so a secret is replaced whole rather than by its prefix
    # or by a shorter secret it contains. Sorted once per call.
    ordered = sorted(needles, key=len, reverse=True)
    return re.compile("|".join(re.escape(n) for n in ordered))


def _redact(value, pattern: re.Pattern):
    if isinstance(value, str):
        return pattern.sub(REDACTED, value)
    if isinstance(value, dict):
        # Keys too: a standard's details can be keyed by whatever it read.
        return {_redact(k, pattern): _redact(v, pattern) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(v, pattern) for v in value]
    return value
