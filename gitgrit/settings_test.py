import os

os.environ["DEBUG"] = "True"
os.environ.setdefault("SECRET_KEY", "test-insecure-key-not-for-production")
# pytest-django forces DEBUG=False at session start, which disables the
# encryption module's SECRET_KEY-derived dev fallback. Pin a static Fernet
# key so tests exercise the production-shape "explicit key" path.
os.environ.setdefault(
    "GITGRIT_ENCRYPTION_KEY",
    "w258ShlYJUj9-j8a4e7-O_Nnsq8Wgd6LWP-6-ZBFFFQ=",
)

from gitgrit.settings import *  # noqa: F401, F403, E402

# model_bakery dispatches on exact field class, not isinstance, so custom
# field subclasses need an explicit generator. EncryptedCharField stores
# strings, so reuse the stock string generator.
BAKER_CUSTOM_FIELDS_GEN = {
    "app.infrastructure.model_fields.EncryptedCharField": "app.infrastructure.model_fields.gen_encrypted_charfield_for_baker",
}
