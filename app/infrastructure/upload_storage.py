"""Where artifact projects' archives live: Django's ``uploads`` storage
(``settings.STORAGES``), keyed by workspace, project and commit SHA."""
from __future__ import annotations

import logging

from django.core.files.base import ContentFile
from django.core.files.storage import storages

logger = logging.getLogger(__name__)


def _storage():
    return storages["uploads"]


def archive_key(tenant_id, project_id, sha: str) -> str:
    return f"{tenant_id}/{project_id}/{sha}"


def save_archive(key: str, data: bytes) -> None:
    """Store ``data`` under ``key``. A commit SHA names its content, so an
    archive already stored under the key is left as is."""
    storage = _storage()
    if not storage.exists(key):
        saved = storage.save(key, ContentFile(data))
        if saved != key:  # lost a race to an identical upload: keep one copy
            storage.delete(saved)


def read_archive(key: str) -> bytes:
    with _storage().open(key, "rb") as f:
        return f.read()


def delete_archive(key: str) -> None:
    """Remove the archive under ``key``. A failure is logged, not raised: the
    commit it belonged to is already gone, so nothing would retry it."""
    try:
        _storage().delete(key)
    except Exception:
        logger.exception("Could not delete uploaded archive %s", key)
