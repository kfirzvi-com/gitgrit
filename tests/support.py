"""Shared helpers for tests written as unittest TestCase subclasses.

CI runs ``manage.py test``, whose unittest loader collects only TestCase
subclasses — bare ``def test_*`` functions are invisible to it and contribute
nothing, silently. Everything here exists to let a test keep using the pytest
conveniences it was written with while living in a class the loader can see.
"""
from __future__ import annotations

import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

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


def commit_status_patch():
    """Stub the platform client the ``run_standards`` job posts the grade
    through (``app.application.grade_alerts``), so a job run in a test never
    reaches GitHub. The stub reports no branch head, so nothing is posted;
    tests of the status itself configure their own client mock."""
    client = mock.Mock()
    client.get_branch_head.return_value = None
    return mock.patch(
        "app.application.grade_alerts.get_platform_client", return_value=client
    )


@contextmanager
def queued_standards_run_inline():
    """Execute background standard runs synchronously, inside the test.

    Standard runs are enqueued as a ``run_standards`` Procrastinate job (see
    ``app.application.standard_runs.enqueue_run``) and executed by the worker,
    which tests don't have. This patches the job's ``configure().defer()`` so
    the deferred call runs the task body immediately — the RUNNING rows are
    created and filled in within the request that triggered them, and a test
    can assert on finished executions the way it would with a real worker.
    The sandbox itself still needs mocking (``SandboxRunner``).
    """
    import logging

    from app import tasks

    def _run_now(**kwargs):
        # Like the worker: a failing job marks its rows ERROR and logs; the
        # request that queued it never sees the exception.
        try:
            tasks.run_standards.func(**kwargs)
        except Exception:
            logging.getLogger(__name__).exception("inline run_standards failed")

    def _configure(**_options):
        stub = mock.Mock()
        stub.defer.side_effect = _run_now
        return stub

    with mock.patch(
        "app.application.standard_runs.run_standards.configure",
        side_effect=_configure,
    ) as configure, commit_status_patch():
        yield configure


def defer_patch(**kwargs):
    """Patch the ``run_standards`` job's ``configure`` so tests can assert what
    was queued without a worker: ``configure.return_value.defer`` records the
    call. ``kwargs`` go to ``mock.patch`` (e.g. ``side_effect``). Pair with
    ``running_executions`` to assert on the rows."""
    return mock.patch("app.application.standard_runs.run_standards.configure", **kwargs)


def running_executions(project=None):
    """The RUNNING execution rows (optionally of one project) — what
    ``enqueue_run`` leaves behind for the worker."""
    from app.domain.models import StandardExecution

    rows = StandardExecution.objects.filter(status=StandardExecution.Status.RUNNING)
    if project is not None:
        rows = rows.filter(project=project)
    return rows
