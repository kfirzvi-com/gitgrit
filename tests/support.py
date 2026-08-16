"""Shared helpers for tests written as unittest TestCase subclasses.

CI runs ``manage.py test``, whose unittest loader collects only TestCase
subclasses — bare ``def test_*`` functions are invisible to it and contribute
nothing, silently. Everything here exists to let a test keep using the pytest
conveniences it was written with while living in a class the loader can see.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from _pytest.monkeypatch import MonkeyPatch


class MonkeyPatchMixin:
    """Provides ``self.monkeypatch``, undone after each test.

    ``MonkeyPatch`` is usable as a plain object outside pytest's fixture
    machinery, so setattr/setenv/chdir/delitem calls convert verbatim rather
    than being hand-translated into mock.patch — which is where a conversion
    would otherwise quietly change behaviour.
    """

    def setUp(self):
        super().setUp()
        self.monkeypatch = MonkeyPatch()
        self.addCleanup(self.monkeypatch.undo)


class TmpPathMixin:
    """Provides ``self.tmp_path`` as a Path, removed after each test.

    The unittest equivalent of pytest's ``tmp_path`` fixture.
    """

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp_path = Path(tmp.name)
