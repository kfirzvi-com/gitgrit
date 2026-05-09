"""Symmetric encryption for sensitive model fields (e.g. OAuth tokens).

Reads its key from ``settings.GITGRIT_ENCRYPTION_KEY`` (a urlsafe-base64-encoded
32-byte Fernet key — generate with ``python -c "from cryptography.fernet import
Fernet; print(Fernet.generate_key().decode())"``). When ``DEBUG`` is true the
key is derived from ``SECRET_KEY`` so local dev works without extra setup;
production deployments must set ``GITGRIT_ENCRYPTION_KEY`` explicitly so that
rotating ``SECRET_KEY`` does not silently invalidate stored ciphertext.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    key = getattr(settings, "GITGRIT_ENCRYPTION_KEY", None)
    if key:
        return Fernet(key.encode())
    if settings.DEBUG:
        logger.warning(
            "GITGRIT_ENCRYPTION_KEY not set; deriving a key from SECRET_KEY for "
            "local development. Do NOT use this mode in any environment that "
            "stores real tokens — rotating SECRET_KEY will orphan all "
            "ciphertext."
        )
        digest = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
        derived = base64.urlsafe_b64encode(digest)
        return Fernet(derived)
    raise RuntimeError(
        "GITGRIT_ENCRYPTION_KEY is required in production. Generate one with "
        "`python -c \"from cryptography.fernet import Fernet; "
        "print(Fernet.generate_key().decode())\"` and set it in your "
        ".kamal/secrets.<dest> file."
    )


def reset_encryption_cache() -> None:
    """Drop the cached Fernet instance.

    Call this from tests that override ``SECRET_KEY`` or
    ``GITGRIT_ENCRYPTION_KEY`` so subsequent ``encrypt``/``decrypt`` calls
    rebuild the Fernet against the new value.
    """
    _fernet.cache_clear()


def encrypt(plaintext: str) -> str:
    """Encrypt ``plaintext`` and return a urlsafe-base64 string."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Decrypt a Fernet token. Raises :class:`InvalidToken` on failure."""
    return _fernet().decrypt(ciphertext.encode()).decode()


def is_our_ciphertext(value: str) -> bool:
    """Return True if ``value`` decrypts cleanly under the current key.

    Used by the lenient field decryption path to distinguish post-migration
    ciphertext from legacy plaintext during the rolling upgrade. Not a security
    boundary — never make trust decisions based on this. After all rows have
    been migrated, plaintext fallback should be removed and ``decrypt`` made
    mandatory.
    """
    if not value:
        return False
    try:
        decrypt(value)
        return True
    except InvalidToken:
        return False
