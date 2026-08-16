"""How the GitHub App private key is carried through env plumbing.

The PEM is multi-line; every transport between a secret store and the running
container is one line per value. Base64 is the only encoding that survives the
whole chain — a shell heredoc and a dotenv parser both sit in the path and both
may consume a backslash level, which silently turns "-----BEGIN RSA PRIVATE
KEY-----\nMIIE..." into "-----BEGIN RSA PRIVATE KEY-----nMIIE..." and fails at
the first signature rather than at startup.

These tests pin the reader, not the plumbing: given each supported form, the
setting must come out as a PEM that actually signs.
"""
from __future__ import annotations

import base64
import importlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import SimpleTestCase


def _pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()


class ReadAppPrivateKeyTests(SimpleTestCase):
    """Exercises the reader directly, so no settings reload is needed."""

    def setUp(self):
        self.settings_module = importlib.import_module("gitgrit.settings")
        self.read = self.settings_module._read_app_private_key
        self.pem = _pem()

    def _with_env(self, **env):
        for k, v in env.items():
            patcher = self.settings_patch(k, v)
            patcher.start()
            self.addCleanup(patcher.stop)

    def settings_patch(self, name, value):
        from unittest import mock

        return mock.patch.dict("os.environ", {name: value}, clear=False)

    def test_base64_form_round_trips_to_the_original_pem(self):
        self._with_env(
            GITHUB_APP_PRIVATE_KEY_B64=base64.b64encode(self.pem.encode()).decode()
        )
        self.assertEqual(self.read(), self.pem)

    def test_base64_wins_over_the_escaped_form(self):
        self._with_env(
            GITHUB_APP_PRIVATE_KEY_B64=base64.b64encode(self.pem.encode()).decode(),
            GITHUB_APP_PRIVATE_KEY="not-the-key",
        )
        self.assertEqual(self.read(), self.pem)

    def test_escaped_form_is_still_understood(self):
        self._with_env(
            GITHUB_APP_PRIVATE_KEY_B64="",
            GITHUB_APP_PRIVATE_KEY=self.pem.replace("\n", "\\n"),
        )
        self.assertEqual(self.read(), self.pem)

    def test_unset_is_empty_not_an_error(self):
        self._with_env(GITHUB_APP_PRIVATE_KEY_B64="", GITHUB_APP_PRIVATE_KEY="")
        self.assertEqual(self.read(), "")

    def test_unreadable_base64_raises_instead_of_silently_disabling(self):
        """A corrupt key must name itself. Returning "" would present as
        "the feature is switched off", which is what made the original
        incident take a redeploy per hypothesis to diagnose."""
        self._with_env(GITHUB_APP_PRIVATE_KEY_B64="!!!! not base64 !!!!")
        with self.assertRaisesRegex(ValueError, "not valid base64"):
            self.read()

    def test_a_key_mangled_by_backslash_stripping_does_not_survive_as_valid(self):
        """Regression guard for the shape the incident produced: the escaped
        form with its backslashes eaten, i.e. newlines replaced by bare "n".
        It must not silently read back as a usable PEM."""
        self._with_env(
            GITHUB_APP_PRIVATE_KEY_B64="",
            GITHUB_APP_PRIVATE_KEY=self.pem.replace("\n", "n"),
        )
        mangled = self.read()
        self.assertNotEqual(mangled, self.pem)
        self.assertNotIn("\n", mangled)


class SigningWithTheDecodedKeyTests(SimpleTestCase):
    """The end that actually matters: the decoded value can sign an App JWT."""

    def test_base64_decoded_key_signs_an_rs256_jwt(self):
        import jwt

        from gitgrit.settings import _read_app_private_key

        pem = _pem()
        from unittest import mock

        with mock.patch.dict(
            "os.environ",
            {"GITHUB_APP_PRIVATE_KEY_B64": base64.b64encode(pem.encode()).decode()},
            clear=False,
        ):
            key = _read_app_private_key()

        token = jwt.encode({"iss": "123", "iat": 0, "exp": 1}, key, algorithm="RS256")
        self.assertTrue(token)

    def test_backslash_stripped_key_cannot_sign(self):
        """Proves the failure mode is a hard error at signing time, which is
        why it never surfaced as a config problem."""
        import jwt

        pem = _pem().replace("\n", "n")
        with self.assertRaises(Exception):
            jwt.encode({"iss": "123"}, pem, algorithm="RS256")
