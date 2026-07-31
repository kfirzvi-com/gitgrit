from __future__ import annotations

import hashlib
import hmac


def verify_github_signature(secret: str, body: bytes, header: str | None) -> bool:
    """Verify a GitHub `X-Hub-Signature-256` header against the raw body.

    Header format is `sha256=<hex>`. Comparison is constant-time.
    """
    if not secret or not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    received = header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


def verify_gitlab_token(secret: str, header: str | None) -> bool:
    """Verify a GitLab `X-Gitlab-Token` header against the configured secret.

    GitLab sends the secret directly (not an HMAC), so this is a constant-time
    string compare.
    """
    if not secret or not header:
        return False
    return hmac.compare_digest(secret, header)
