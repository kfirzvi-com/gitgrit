"""Where upload projects' archives live: Django's ``uploads`` storage
(``settings.STORAGES``), keyed by workspace, project and version digest."""
from __future__ import annotations

from django.core.files.base import ContentFile
from django.core.files.storage import storages


def _storage():
    return storages["uploads"]


def archive_key(tenant_id, project_id, digest: str) -> str:
    return f"{tenant_id}/{project_id}/{digest}"


def save_archive(key: str, data: bytes) -> None:
    """Store ``data`` under ``key``. A digest names its content, so an
    archive already stored under the key is left as is."""
    storage = _storage()
    if not storage.exists(key):
        saved = storage.save(key, ContentFile(data))
        if saved != key:  # lost a race to an identical upload: keep one copy
            storage.delete(saved)


def read_archive(key: str) -> bytes:
    with _storage().open(key, "rb") as f:
        return f.read()
