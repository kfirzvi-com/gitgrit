from __future__ import annotations

import os
from unittest import mock

import pytest
from cryptography.fernet import Fernet, InvalidToken
from django.db import connection
from django.test import TestCase
from model_bakery import baker

from app.domain.models import PlatformConnection
from app.infrastructure import encryption
from app.infrastructure.model_fields import EncryptedCharField


class TestEncryptHelpers:
    def test_round_trip(self):
        ciphertext = encryption.encrypt("ghp_secrettoken")
        assert ciphertext != "ghp_secrettoken"
        assert ciphertext.startswith("gAAAAA")
        assert encryption.decrypt(ciphertext) == "ghp_secrettoken"

    def test_decrypt_garbage_raises(self):
        with pytest.raises(InvalidToken):
            encryption.decrypt("not-a-fernet-token")

    def test_is_our_ciphertext_recognises_own_output(self):
        ciphertext = encryption.encrypt("hello")
        assert encryption.is_our_ciphertext(ciphertext) is True
        assert encryption.is_our_ciphertext("not-our-token") is False
        assert encryption.is_our_ciphertext("") is False

    def test_is_our_ciphertext_rejects_token_under_different_key(self):
        # A Fernet token that's structurally valid but encrypted under a
        # different key must not be accepted.
        other = Fernet(Fernet.generate_key())
        foreign = other.encrypt(b"hello").decode()
        assert encryption.is_our_ciphertext(foreign) is False

    def test_missing_key_raises_in_production_mode(self):
        # Pretend we're not in DEBUG and the env var is absent. The cached
        # Fernet must be cleared so the new state is observed.
        with (
            mock.patch.dict(os.environ, {}, clear=False),
            mock.patch.object(encryption.settings, "DEBUG", False),
        ):
            os.environ.pop("GITGRIT_ENCRYPTION_KEY", None)
            encryption.reset_encryption_cache()
            with pytest.raises(RuntimeError, match="GITGRIT_ENCRYPTION_KEY"):
                encryption.encrypt("anything")
        encryption.reset_encryption_cache()


class TestEncryptedCharFieldRoundTrip(TestCase):
    """Pin the contract: ciphertext at rest, plaintext on the Python attribute."""

    def test_value_is_ciphertext_in_db_and_plaintext_on_read(self):
        conn = baker.make(
            "app.PlatformConnection",
            platform="github",
            access_token="ghp_my-real-token",
        )

        with connection.cursor() as cur:
            cur.execute(
                "SELECT access_token FROM platform_connections WHERE id = %s",
                [str(conn.id)],
            )
            raw_db_value = cur.fetchone()[0]

        assert raw_db_value.startswith("gAAAAA"), "DB row must hold ciphertext"
        assert raw_db_value != "ghp_my-real-token"
        assert PlatformConnection.objects.get(pk=conn.pk).access_token == "ghp_my-real-token"

    def test_empty_string_is_not_encrypted(self):
        conn = baker.make("app.PlatformConnection", platform="github", access_token="")
        with connection.cursor() as cur:
            cur.execute(
                "SELECT access_token FROM platform_connections WHERE id = %s",
                [str(conn.id)],
            )
            raw_db_value = cur.fetchone()[0]
        assert raw_db_value == ""
        assert PlatformConnection.objects.get(pk=conn.pk).access_token == ""

    def test_legacy_plaintext_is_read_leniently(self):
        # Simulate a row that predates the encrypted-field migration by writing
        # plaintext directly to the DB, bypassing get_prep_value.
        conn = baker.make(
            "app.PlatformConnection",
            platform="github",
            access_token="anything",
        )
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE platform_connections SET access_token = %s WHERE id = %s",
                ["ghp_legacy-plaintext", str(conn.id)],
            )

        # from_db_value must return the plaintext verbatim rather than crashing.
        loaded = PlatformConnection.objects.get(pk=conn.pk)
        assert loaded.access_token == "ghp_legacy-plaintext"

    def test_resaving_legacy_row_encrypts_it(self):
        conn = baker.make(
            "app.PlatformConnection",
            platform="github",
            access_token="anything",
        )
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE platform_connections SET access_token = %s WHERE id = %s",
                ["ghp_legacy", str(conn.id)],
            )

        # The migration's "re-save every row" loop pattern.
        loaded = PlatformConnection.objects.get(pk=conn.pk)
        loaded.save(update_fields=["access_token"])

        with connection.cursor() as cur:
            cur.execute(
                "SELECT access_token FROM platform_connections WHERE id = %s",
                [str(conn.id)],
            )
            raw = cur.fetchone()[0]
        assert raw.startswith("gAAAAA")
        assert PlatformConnection.objects.get(pk=conn.pk).access_token == "ghp_legacy"

    def test_resaving_already_encrypted_row_does_not_double_encrypt(self):
        conn = baker.make(
            "app.PlatformConnection",
            platform="github",
            access_token="ghp_already-encrypted",
        )
        loaded = PlatformConnection.objects.get(pk=conn.pk)
        loaded.save(update_fields=["access_token"])
        # The plaintext on read must still be the original — not double-decrypted
        # (which would either fail to decrypt or yield ciphertext-as-plaintext).
        assert PlatformConnection.objects.get(pk=conn.pk).access_token == "ghp_already-encrypted"


class TestEncryptedCharFieldInherits:
    def test_is_a_charfield_subclass(self):
        # Pinned so `isinstance(f, CharField)` checks elsewhere keep working.
        from django.db import models
        assert issubclass(EncryptedCharField, models.CharField)
