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


class Patches:
    """Several ``mock.patch`` objects entered as one context manager.

    Reusable, unlike a ``@contextmanager`` generator: tests here build a tuple
    of patches once and enter it in several ``with`` blocks.
    """

    def __init__(self, *patches):
        self._patches = patches

    def __enter__(self):
        for patch in self._patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in reversed(self._patches):
            patch.stop()
        return False


def administers_account(administers=True):
    """Patch GitHub's answer to "does this user administer that account".

    Entitlement to a GitHub App installation is not "can you reach it" —
    ``GET /user/installations`` says yes to an outside collaborator on a single
    repository, while a connection holds the whole installation, mints
    installation-wide tokens, and lists the installation's own repositories in
    Add Project. So the flows also ask whether the user owns the account it sits
    on, and a fixture describing an entitled user has to answer that.

    Both seams are patched, because the two flows ask through different doors:
    a callback holds only an installation id, while the picker holds a list of
    accounts and asks one cached ``AccountAuthority`` about each.

    Defaults to True: the account owner or org admin, for whom connecting grants
    nothing they were not already entitled to.
    """
    from unittest import mock

    from app.infrastructure import github_app

    return Patches(
        mock.patch.object(
            github_app, "user_administers_installation", return_value=administers
        ),
        mock.patch.object(
            github_app.AccountAuthority, "administers", return_value=administers
        ),
    )
