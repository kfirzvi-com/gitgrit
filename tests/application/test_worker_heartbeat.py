"""The worker liveness thread matches the CloudWatch filter without a queue job.

The alarm counts worker-log lines containing both
``expire_stale_standard_runs`` and ``ended with status: Success``. These tests
lock that text, and the decision that a busy loop still emits while a wedged
loop and a dead thread do not.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import threading
import time

from django.conf import settings
from django.core.management import get_commands
from django.test import SimpleTestCase
from procrastinate.contrib.django import app as procrastinate_app
from procrastinate.contrib.django import procrastinate_app as django_procrastinate

import app.worker_heartbeat as heartbeat_module
from app.worker_heartbeat import (
    HEARTBEAT_FILTER_PHRASES,
    HEARTBEAT_MESSAGE,
    WorkerHeartbeat,
    install_worker_heartbeat,
    is_worker_command,
)


def _messages(records: list[logging.LogRecord]) -> list[str]:
    return [record.getMessage() for record in records]


class _LoopThread:
    """Run an event loop on a background thread, the way the worker does."""

    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self._ready.set()
        self.loop.run_forever()

    def start(self) -> _LoopThread:
        self._thread.start()
        if not self._ready.wait(2):
            raise RuntimeError("event loop thread did not start")
        return self

    def stop(self) -> None:
        release = getattr(self, "_release_wedge", None)
        if release is not None:
            release.set()
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(2)
        if not self.loop.is_closed():
            self.loop.close()

    def wedge(self) -> None:
        """Block the loop thread until ``release`` is set."""
        self._release_wedge = threading.Event()
        entered = threading.Event()

        def block() -> None:
            entered.set()
            self._release_wedge.wait(30)

        self.loop.call_soon_threadsafe(block)
        if not entered.wait(2):
            raise RuntimeError("loop did not enter the wedge")

    def release(self) -> None:
        self._release_wedge.set()


class HeartbeatContractTests(SimpleTestCase):
    def test_message_contains_both_filter_phrases_and_not_the_error_phrase(self):
        self.assertEqual(
            HEARTBEAT_FILTER_PHRASES,
            ("expire_stale_standard_runs", "ended with status: Success"),
        )
        for phrase in HEARTBEAT_FILTER_PHRASES:
            self.assertIn(phrase, HEARTBEAT_MESSAGE)
        # WorkerJobErrors matches "ended with status: Error". A liveness line
        # must not count as a failed job.
        self.assertNotIn("ended with status: Error", HEARTBEAT_MESSAGE)
        self.assertTrue(HEARTBEAT_MESSAGE.startswith("worker liveness: "))

    def test_production_formatter_keeps_both_phrases_on_one_line(self):
        formatter_cfg = settings.LOGGING["formatters"]["timestamped"]
        formatter = logging.Formatter(
            formatter_cfg["format"],
            datefmt=formatter_cfg["datefmt"],
            style="{",
        )
        record = logging.LogRecord(
            name="procrastinate.worker",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=HEARTBEAT_MESSAGE,
            args=(),
            exc_info=None,
        )
        line = formatter.format(record)
        for phrase in HEARTBEAT_FILTER_PHRASES:
            self.assertIn(phrase, line)
        self.assertIn("procrastinate.worker", line)
        self.assertNotIn("\n", line)

    def test_procrastinate_worker_logger_emits_info_to_the_console_handler(self):
        # The metric filter reads the worker log group, which is this
        # handler's stderr. Dropping INFO here would silence the heartbeat
        # without an infra change.
        cfg = settings.LOGGING["loggers"]["procrastinate.worker"]
        self.assertEqual(cfg["level"], "INFO")
        self.assertIn("console_timestamped", cfg["handlers"])
        self.assertFalse(cfg["propagate"])


class HeartbeatThreadTests(SimpleTestCase):
    def setUp(self):
        self.loop_thread = _LoopThread().start()
        self.addCleanup(self.loop_thread.stop)

    def _heartbeat(self, **kwargs) -> WorkerHeartbeat:
        heartbeat = WorkerHeartbeat(self.loop_thread.loop, **kwargs)
        self.addCleanup(heartbeat.stop)
        return heartbeat

    def test_emits_immediately_and_again_on_the_interval_from_a_daemon_thread(self):
        heartbeat = self._heartbeat(interval=0.05, loop_timeout=1)
        with self.assertLogs("procrastinate.worker", level="INFO") as logs:
            heartbeat.start()
            self.assertIsNotNone(heartbeat._thread)
            assert heartbeat._thread is not None
            self.assertTrue(heartbeat._thread.daemon)
            self.assertEqual(heartbeat._thread.name, "gitgrit-worker-heartbeat")
            deadline = time.monotonic() + 2
            while len(logs.records) < 2 and time.monotonic() < deadline:
                time.sleep(0.01)
            heartbeat.stop()

        messages = _messages(logs.records)
        self.assertGreaterEqual(len(messages), 2)
        for message in messages:
            self.assertEqual(message, HEARTBEAT_MESSAGE)
        assert heartbeat._thread is not None
        self.assertFalse(heartbeat._thread.is_alive())

    def test_stop_is_idempotent_and_emits_nothing_afterwards(self):
        heartbeat = self._heartbeat(interval=0.05, loop_timeout=1)
        with self.assertLogs("procrastinate.worker", level="INFO") as logs:
            heartbeat.start()
            deadline = time.monotonic() + 2
            while not logs.records and time.monotonic() < deadline:
                time.sleep(0.01)
            heartbeat.stop()
            heartbeat.stop()
        self.assertTrue(logs.records)

        with self.assertNoLogs("procrastinate.worker", level="INFO"):
            time.sleep(0.15)

    def test_busy_loop_still_emits(self):
        """A long call on a worker thread must not look like a dead worker."""
        heartbeat = self._heartbeat(interval=60, loop_timeout=1)
        started = threading.Event()
        release = threading.Event()

        async def occupy_a_thread() -> None:
            def block() -> None:
                started.set()
                release.wait(5)

            await asyncio.to_thread(block)

        fut = asyncio.run_coroutine_threadsafe(occupy_a_thread(), self.loop_thread.loop)
        self.addCleanup(release.set)
        self.addCleanup(fut.cancel)
        self.assertTrue(started.wait(2))

        with self.assertLogs("procrastinate.worker", level="INFO") as logs:
            heartbeat.start()
            deadline = time.monotonic() + 2
            while not logs.records and time.monotonic() < deadline:
                time.sleep(0.01)
            heartbeat.stop()

        self.assertEqual(_messages(logs.records), [HEARTBEAT_MESSAGE])
        release.set()
        fut.result(timeout=2)

    def test_wedged_loop_does_not_emit_and_stop_returns_promptly(self):
        self.loop_thread.wedge()
        self.addCleanup(self.loop_thread.release)
        heartbeat = self._heartbeat(interval=0.05, loop_timeout=2)
        with self.assertNoLogs("procrastinate.worker", level="INFO"):
            heartbeat.start()
            time.sleep(0.2)
            started = time.monotonic()
            heartbeat.stop()
            self.assertLess(time.monotonic() - started, 1.0)
        assert heartbeat._thread is not None
        self.assertFalse(heartbeat._thread.is_alive())

    def test_closed_loop_does_not_emit_or_kill_the_thread(self):
        self.loop_thread.stop()
        heartbeat = self._heartbeat(interval=0.05, loop_timeout=0.2)
        with self.assertNoLogs("procrastinate.worker", level="INFO"):
            heartbeat.start()
            time.sleep(0.15)
            self.assertTrue(heartbeat._thread is not None and heartbeat._thread.is_alive())
            heartbeat.stop()
        assert heartbeat._thread is not None
        self.assertFalse(heartbeat._thread.is_alive())


def _code_filename(fn: object) -> str:
    code = getattr(fn, "__code__", None)
    if code is None:
        code = fn.__func__.__code__  # type: ignore[attr-defined]
    return code.co_filename.replace("\\", "/")


class WorkerInstallTests(SimpleTestCase):
    """The heartbeat is installed from AppConfig.ready, not a command override.

    Django keeps the management command from the earliest installed app, and
    ``procrastinate.contrib.django`` is listed before ``app``. The command
    then calls ``run_worker_async`` on ``current_app``, not on the proxy.
    """

    def setUp(self):
        self._app = django_procrastinate.current_app
        self._original = self._app.run_worker_async
        self._was_installed = heartbeat_module._installed
        self.addCleanup(self._restore)

    def _restore(self):
        self._app.run_worker_async = self._original
        heartbeat_module._installed = self._was_installed

    def test_only_the_worker_subcommand_counts(self):
        worker = [
            "manage.py",
            "procrastinate",
            "worker",
            "--queues=graph,standards,notifications",
            "--concurrency",
            "1",
        ]
        self.assertTrue(is_worker_command(worker))
        self.assertFalse(is_worker_command(["manage.py", "procrastinate", "healthchecks"]))
        self.assertFalse(is_worker_command(["manage.py", "procrastinate", "defer", "worker_task"]))
        self.assertFalse(is_worker_command(["manage.py", "runserver"]))
        self.assertFalse(
            is_worker_command(
                ["manage.py", "test", "tests.application.test_worker_heartbeat"]
            )
        )
        # The subcommand is the next token, not a later argument that happens
        # to contain the word.
        self.assertFalse(is_worker_command(["manage.py", "procrastinate", "defer", "worker"]))

    def test_django_keeps_the_upstream_procrastinate_command(self):
        self.assertEqual(get_commands()["procrastinate"], "procrastinate.contrib.django")

    def test_install_wraps_the_worker_and_a_second_call_does_not_stack(self):
        seen: dict[str, object] = {}

        async def worker(**kwargs):
            seen["kwargs"] = kwargs
            seen["threads"] = [
                thread.name
                for thread in threading.enumerate()
                if thread.name == "gitgrit-worker-heartbeat"
            ]
            await asyncio.sleep(0.5)

        self._app.run_worker_async = worker
        argv = ["manage.py", "procrastinate", "worker"]
        self.assertTrue(install_worker_heartbeat(argv))
        self.assertFalse(install_worker_heartbeat(argv))

        with self.assertLogs("procrastinate.worker", level="INFO") as logs:
            asyncio.run(self._app.run_worker_async(queues=["standards"]))

        self.assertEqual(seen["kwargs"], {"queues": ["standards"]})
        self.assertEqual(seen["threads"], ["gitgrit-worker-heartbeat"])
        self.assertIn(HEARTBEAT_MESSAGE, _messages(logs.records))
        with self.assertNoLogs("procrastinate.worker", level="INFO"):
            time.sleep(0.05)

    def test_install_stops_the_heartbeat_when_the_worker_raises(self):
        async def worker(**kwargs):
            await asyncio.sleep(0.5)
            raise RuntimeError("worker failed")

        self._app.run_worker_async = worker
        self.assertTrue(install_worker_heartbeat(["manage.py", "procrastinate", "worker"]))
        with self.assertLogs("procrastinate.worker", level="INFO") as logs:
            with self.assertRaisesRegex(RuntimeError, "worker failed"):
                asyncio.run(self._app.run_worker_async())

        self.assertIn(HEARTBEAT_MESSAGE, _messages(logs.records))
        alive = [
            thread
            for thread in threading.enumerate()
            if thread.name == "gitgrit-worker-heartbeat"
        ]
        self.assertEqual(alive, [])

    def test_other_commands_do_not_wrap_the_worker(self):
        stub = self._app.run_worker_async
        with self.assertNoLogs("procrastinate.worker", level="INFO"):
            self.assertFalse(install_worker_heartbeat(["manage.py", "runserver"]))
            self.assertFalse(
                install_worker_heartbeat(["manage.py", "procrastinate", "healthchecks"])
            )
        self.assertIs(self._app.run_worker_async, stub)
        self.assertFalse(heartbeat_module._installed)

    def test_startup_installs_only_for_the_worker_process(self):
        # A fresh interpreter, so AppConfig.ready runs against this argv.
        # The current process was started as ``manage.py test`` and must not
        # have wrapped the worker.
        self.assertFalse(heartbeat_module._installed)
        self.assertIn("procrastinate/app.py", _code_filename(self._app.run_worker_async))

        worker = self._setup_with_argv(
            [
                "manage.py",
                "procrastinate",
                "worker",
                "--queues=graph,standards,notifications",
                "--concurrency",
                "1",
            ]
        )
        self.assertEqual(worker.returncode, 0, worker.stderr)
        self.assertEqual(worker.stdout.strip(), "wrapped")

        web = self._setup_with_argv(["manage.py", "runserver"])
        self.assertEqual(web.returncode, 0, web.stderr)
        self.assertEqual(web.stdout.strip(), "not-wrapped")

    def _setup_with_argv(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        script = """
import os, sys
sys.argv = %r
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "gitgrit.settings_test")
import django
django.setup()
from procrastinate.contrib.django import procrastinate_app as django_procrastinate
fn = django_procrastinate.current_app.run_worker_async
code = getattr(fn, "__code__", None) or fn.__func__.__code__
name = code.co_filename.replace("\\\\", "/")
print("wrapped" if name.endswith("app/worker_heartbeat.py") else "not-wrapped")
""" % (argv,)
        return subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            text=True,
            env=os.environ.copy(),
            check=False,
        )


class StaleSweepKeptTests(SimpleTestCase):
    def test_expire_stale_standard_runs_stays_periodic_on_the_standards_queue(self):
        # Importing tasks registers the periodic job. It is the stale-run
        # sweep, not a heartbeat, so the thread does not replace it.
        import app.tasks  # noqa: F401

        task = procrastinate_app.tasks["expire_stale_standard_runs"]
        self.assertEqual(task.queue, "standards")
        periodic = [
            item
            for item in procrastinate_app.periodic_registry.periodic_tasks.values()
            if item.task.name == "expire_stale_standard_runs"
        ]
        self.assertEqual([item.cron for item in periodic], ["*/5 * * * *"])
