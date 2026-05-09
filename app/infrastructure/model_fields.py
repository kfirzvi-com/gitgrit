"""Custom Django model fields used across the project."""
from __future__ import annotations

import logging

from cryptography.fernet import InvalidToken
from django.db import models

from app.infrastructure.encryption import decrypt, encrypt, is_our_ciphertext

logger = logging.getLogger(__name__)


class EncryptedCharField(models.CharField):
    """A CharField that transparently encrypts at rest with Fernet.

    During the v0.1 rolling migration the read path is lenient: rows that do
    not decrypt under the current key are returned verbatim and a warning is
    logged. After the data migration in ``app/migrations/0015_*`` runs against
    every connection, all rows are ciphertext and the lenient path becomes
    cold. The lenient fallback should be removed once we ship a "strict mode"
    flag (see SECURITY.md follow-ups).
    """

    description = "CharField encrypted at rest with Fernet"

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        try:
            return decrypt(value)
        except InvalidToken:
            logger.warning(
                "EncryptedCharField read legacy plaintext on %s — re-save the "
                "row to encrypt it.",
                self,
            )
            return value

    def get_prep_value(self, value):
        if value in (None, ""):
            return value
        # Skip re-encryption when the value is already ciphertext we issued —
        # e.g. when an instance is saved twice without reload between saves.
        # A user-supplied token would have to coincidentally pass Fernet's
        # `gAAAAA…` prefix and HMAC validation under our key, which is
        # cryptographically negligible.
        if is_our_ciphertext(value):
            return value
        return encrypt(value)


def gen_encrypted_charfield_for_baker() -> str:
    """model_bakery generator for ``EncryptedCharField``.

    Returns a short, fixed plaintext so the resulting Fernet ciphertext fits
    comfortably in the column. The default ``gen_string`` honors ``max_length``
    and produces strings that exceed the column once encrypted (Fernet adds
    ~140 bytes of overhead). Wired up via ``BAKER_CUSTOM_FIELDS_GEN`` in
    ``gitgrit/settings_test.py``.
    """
    return "test-token"
