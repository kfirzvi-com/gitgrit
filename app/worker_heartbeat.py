"""In-process liveness signal for the CloudWatch worker heartbeat alarm.

The alarm ``gitgrit-*-worker-heartbeat-missing`` (2 consecutive 300s windows,
sum < 1, missing data breaches) counts log lines in the worker log group that
contain both ``expire_stale_standard_runs`` and ``ended with status: Success``.
That filter is defined in the infra repo (``modules/cloudwatch-logs``); this
module emits a line that matches it, so the alarm does not need to change.

Those phrases used to arrive only when the periodic ``expire_stale_standard_runs``
job finished. That job sits on the ``standards`` queue, and the worker runs
one job at a time, so a long standard run held the line back long enough for
the alarm to fire while the process was healthy (2026-11-20).

This thread logs the same phrases about once a minute. It does not defer a
job, take a queue slot, or start a sandbox.

When the signal stops
----------------------
The thread is a daemon. Process death (exit, SIGKILL, OOM) stops it with the
process, and the alarm fires.

A wedged event loop also stops it. Each beat asks the worker loop to run a
no-op via ``call_soon_threadsafe`` and skips the log line if that callback
does not run within ``LOOP_LIVENESS_TIMEOUT_SECONDS``. Procrastinate runs sync
tasks (including ``run_standards``) off the loop, on a thread pool, so a busy
slot still lets the loop answer. A loop blocked on its own thread cannot
fetch or finish jobs; that is the stuck worker the alarm is for, and it must
not keep the alarm green.

A loop that still runs callbacks but has stopped fetching jobs is not treated
as dead. That case is indistinguishable from a healthy worker whose only slot
is occupied, which is the false alarm this exists to remove. Procrastinate's
own database heartbeat (see ``STALE_WORKER_SECONDS``) still covers a worker
that has stopped updating ``procrastinate_workers``.
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
from typing import Any

# Same logger Procrastinate uses for "Job … ended with status: Success".
# ``gitgrit.settings.LOGGING`` emits it at INFO through the timestamped
# console handler, which is what the worker log group collects.
logger = logging.getLogger("procrastinate.worker")

# CloudWatch metric filter WorkerHeartbeat, verbatim. A log event must
# contain both phrases. Do not reword them.
HEARTBEAT_FILTER_PHRASES = (
    "expire_stale_standard_runs",
    "ended with status: Success",
)

# Prefixed so a person reading the worker log can tell this apart from the
# real sweep job, whose success line also matches the filter.
HEARTBEAT_MESSAGE = "worker liveness: " + " ".join(HEARTBEAT_FILTER_PHRASES)

# The alarm window is 300s and needs one matching line. A beat a minute
# leaves several points in each window, so one skipped beat does not page.
HEARTBEAT_INTERVAL_SECONDS = 60.0

# Longer than a slow callback, shorter than the alarm window. Sync jobs do
# not run on the loop, so a healthy worker answers in milliseconds.
LOOP_LIVENESS_TIMEOUT_SECONDS = 30.0

# How often to re-check the stop flag while waiting on the loop. Short so
# shutdown does not sit out the liveness timeout: stop() is called on the
# loop thread, and that thread cannot run the callback while it is joining.
_STOP_POLL_SECONDS = 0.05

# Set once install_worker_heartbeat has wrapped the worker entry point.
_installed = False


def is_worker_command(argv: list[str] | None = None) -> bool:
    """True when this process is ``manage.py procrastinate worker``.

    The subcommand is the token immediately after ``procrastinate``, which is
    how Kamal starts the worker (``config/deploy.yml``). A queue or task named
    ``worker`` later in the arguments does not count.
    """
    args = [arg.rsplit("/", 1)[-1] for arg in (sys.argv if argv is None else argv)]
    try:
        index = args.index("procrastinate")
    except ValueError:
        return False
    return args[index + 1 : index + 2] == ["worker"]


def install_worker_heartbeat(argv: list[str] | None = None) -> bool:
    """Wrap ``run_worker_async`` so the worker process heartbeats.

    Called from ``AppConfig.ready``. Django's command lookup keeps the
    ``procrastinate`` command from ``procrastinate.contrib.django``, which is
    listed before ``app``, so this cannot be a management-command override.

    Returns whether this call installed the wrapper. Later calls do nothing,
    so a second ``ready`` cannot stack threads.

    The object ``procrastinate.contrib.django.app`` is a proxy. The management
    command opens it and then calls ``run_worker_async`` on the app that
    context yields, which is ``current_app``. Wrapping the proxy does not
    change that call.
    """
    global _installed
    if _installed or not is_worker_command(argv):
        return False

    from procrastinate import App
    from procrastinate.contrib.django import procrastinate_app as django_procrastinate

    real = django_procrastinate.current_app
    # ``app`` is after ``procrastinate.contrib.django`` in INSTALLED_APPS, so
    # this runs once the blueprint has been replaced by the real app. Before
    # that, current_app is not what the worker command will call.
    if not isinstance(real, App):
        return False

    original = real.run_worker_async

    async def run_worker_async(**worker_kwargs: Any) -> Any:
        heartbeat = WorkerHeartbeat(asyncio.get_running_loop())
        heartbeat.start()
        try:
            return await original(**worker_kwargs)
        finally:
            heartbeat.stop()

    real.run_worker_async = run_worker_async  # type: ignore[method-assign]
    _installed = True
    return True


class WorkerHeartbeat:
    """Daemon thread that logs :data:`HEARTBEAT_MESSAGE` while the loop is alive."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        *,
        interval: float = HEARTBEAT_INTERVAL_SECONDS,
        loop_timeout: float = LOOP_LIVENESS_TIMEOUT_SECONDS,
    ) -> None:
        self._loop = loop
        self._interval = interval
        self._loop_timeout = loop_timeout
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="gitgrit-worker-heartbeat",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Ask the thread to exit and wait for it. Safe to call more than once."""
        self._stop.set()
        thread = self._thread
        if thread is None or thread is threading.current_thread():
            return
        # The thread wakes on the stop flag within one poll, including when
        # it is waiting out a wedged loop. The timeout is only a backstop.
        thread.join(timeout=self._loop_timeout + 1)
        if thread.is_alive():
            logger.warning("worker liveness heartbeat thread did not stop")

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                if self._loop_is_responsive() and not self._stop.is_set():
                    logger.info(HEARTBEAT_MESSAGE)
                if self._stop.wait(self._interval):
                    return
        except Exception:
            # Fail toward the alarm: a dead thread stops emitting. The text
            # must not itself match the heartbeat filter.
            logger.exception("worker liveness heartbeat stopped")

    def _loop_is_responsive(self) -> bool:
        """True when the worker loop runs a callback before timeout or stop."""
        if self._stop.is_set() or self._loop.is_closed():
            return False
        acknowledged = threading.Event()
        try:
            self._loop.call_soon_threadsafe(acknowledged.set)
        except RuntimeError:
            # Loop is closed, or closing.
            return False
        deadline = time.monotonic() + self._loop_timeout
        while not self._stop.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if acknowledged.wait(min(_STOP_POLL_SECONDS, remaining)):
                return not self._stop.is_set()
        return False
