"""Lightweight name normalization (no heavy deps — safe to import anywhere).

Used to dedup external-service names across the workspace so variants like
"Stripe" and "Stripe API" collapse to one node.
"""
from __future__ import annotations

import re

_GENERIC_WORDS = {"api", "service", "sdk", "the", "platform", "inc", "io"}


def canonical_key(name: str) -> str:
    """A dedup key: lowercased, parentheticals dropped, trailing generic words
    removed. ``"Stripe"`` and ``"Stripe API"`` → ``"stripe"``."""
    n = (name or "").lower()
    n = re.sub(r"\([^)]*\)", " ", n)  # drop "(...)"
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    words = [w for w in n.split() if w not in _GENERIC_WORDS]
    return " ".join(words) or n.strip()
