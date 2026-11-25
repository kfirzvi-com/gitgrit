from __future__ import annotations

from app.application.delivery.source_unavailable import SourceUnavailable


class TokenRefused(SourceUnavailable):
    """The platform refused the connection's credentials (expired or
    revoked). Nothing else can be read with them, so a sync stops at the
    first refusal rather than asking again for every kind of data."""
