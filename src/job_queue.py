"""A small, persistent, bounded job queue for download requests.

Why this exists (from the project's requirements):

- "Use a queue when a request comes in": every download request goes through
  a fixed-size pool of workers (``Config.queue_workers``) instead of each
  Telegram message spawning its own unbounded thread, so a burst of links
  cannot pile up unlimited concurrent ffmpeg/pytubefix work.
- "Don't oversaturate on reconnect after a power cut, just send an error":
  every accepted job is written to a tiny SQLite journal before it starts
  running. If the process dies mid-download (crash, power loss, OOM-kill),
  that row survives. On the NEXT startup, ``recover_stale_jobs`` finds it,
  tells the affected chat their request was interrupted, and discards the
  row -- it deliberately never auto-resumes a job, which is exactly the
  behaviour that would "oversaturate" calls after an unclean restart.
- Bounded size: once ``Config.queue_max_size`` jobs are waiting,
  ``submit()`` raises ``QueueFullError`` instead of growing forever, so the
  caller can tell the user to try again shortly.

This module is intentionally free of any Telegram/PTB imports so it can be
unit-tested on its own.
"""

from __future__ import annotations

import asyncio
import logging
import sqlite3
import threading
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class QueueFullError(RuntimeError):
    """Raised by ``submit()`` when the queue is at capacity."""


@dataclass(frozen=True)
class JobRecord:
    job_id: str
    chat_id: int
    user_id: int
    payload: str
    created_at: str


# A job handler receives the job's payload (e.g. a YouTube URL) and does the
# actual work. It is expected to report its own success/failure to the user
# (e.g. by editing a status message) -- the queue only guarantees it runs
# with bounded concurrency and that the journal entry is cleaned up after.
JobHandler = Callable[[str], Awaitable[None]]
StartCallback = Callable[[JobRecord], Awaitable[None]]
StaleCallback = Callable[[JobRecord], Awaitable[None]]


class JobQueue:
    """Bounded FIFO queue with a SQLite-backed crash-recovery journal."""

    def __init__(
        self,
        db_path: str | Path = "database/queue.db",
        max_size: int = 50,
        workers: int = 2,
        job_timeout_seconds: float | None = 1800.0,
    ):
        self._max_size = max_size
        self._workers = workers
        self._job_timeout = job_timeout_seconds

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # One connection shared across worker tasks, guarded by a lock. The
        # journal only ever holds a handful of rows and every operation is a
        # single-row write, so a plain lock (rather than a thread pool) is
        # simple and fast enough.
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._db_lock = threading.Lock()
        self._create_schema()

        self._queue: asyncio.Queue[tuple[JobRecord, JobHandler, StartCallback | None]] = (
            asyncio.Queue(maxsize=max_size)
        )
        self._worker_tasks: list[asyncio.Task] = []

    # =========================================================================
    # Schema / journal
    # =========================================================================

    def _create_schema(self) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def _insert(self, job: JobRecord) -> None:
        with self._db_lock:
            self._conn.execute(
                """
                INSERT INTO jobs (job_id, chat_id, user_id, payload, status, created_at)
                VALUES (?, ?, ?, ?, 'queued', ?)
                """,
                (job.job_id, job.chat_id, job.user_id, job.payload, job.created_at),
            )
            self._conn.commit()

    def _mark_processing(self, job_id: str) -> None:
        with self._db_lock:
            self._conn.execute(
                "UPDATE jobs SET status = 'processing' WHERE job_id = ?",
                (job_id,),
            )
            self._conn.commit()

    def _delete(self, job_id: str) -> None:
        with self._db_lock:
            self._conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            self._conn.commit()

    def _fetch_all(self) -> list[JobRecord]:
        with self._db_lock:
            rows = self._conn.execute(
                "SELECT job_id, chat_id, user_id, payload, created_at FROM jobs"
            ).fetchall()

        return [JobRecord(*row) for row in rows]

    # =========================================================================
    # Crash recovery
    # =========================================================================

    async def recover_stale_jobs(self, on_stale: StaleCallback) -> int:
        """Find jobs left behind by an unclean shutdown and clear them.

        Call this ONCE at startup, before ``start()``. Every leftover row --
        whether it was still waiting or already being processed when the
        process died -- is lost work: the in-memory queue that would have
        run it no longer exists. Rather than guessing and re-running it
        (which is exactly the "oversaturate calls on reconnect" failure mode
        this design avoids), each one is reported to ``on_stale`` (normally:
        tell the user their request was interrupted) and then discarded.
        """
        stale_jobs = await asyncio.to_thread(self._fetch_all)

        for job in stale_jobs:
            try:
                await on_stale(job)
            except Exception:
                logger.exception("on_stale callback failed for job %s", job.job_id)

            await asyncio.to_thread(self._delete, job.job_id)

        if stale_jobs:
            logger.warning(
                "Recovered %d stale job(s) from an unclean shutdown.", len(stale_jobs)
            )

        return len(stale_jobs)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def start(self) -> None:
        """Start the worker pool. Call ``recover_stale_jobs`` first."""
        if self._worker_tasks:
            return

        self._worker_tasks = [
            asyncio.create_task(self._worker_loop(name=f"job-worker-{i}"))
            for i in range(self._workers)
        ]

        logger.info("Job queue started with %d worker(s).", self._workers)

    async def stop(self) -> None:
        """Cancel all workers. In-flight jobs are abandoned; their journal
        rows remain and will be picked up by ``recover_stale_jobs`` on the
        next startup."""
        for task in self._worker_tasks:
            task.cancel()

        for task in self._worker_tasks:
            with suppress(asyncio.CancelledError):
                await task

        self._worker_tasks.clear()

    def close(self) -> None:
        self._conn.close()

    # =========================================================================
    # Submitting work
    # =========================================================================

    @property
    def waiting(self) -> int:
        """Jobs currently sitting in the queue (not counting ones a worker
        has already picked up)."""
        return self._queue.qsize()

    @property
    def capacity(self) -> int:
        return self._max_size

    async def submit(
        self,
        chat_id: int,
        user_id: int,
        payload: str,
        handler: JobHandler,
        on_start: StartCallback | None = None,
    ) -> JobRecord:
        """Enqueue a job.

        ``handler(payload)`` is awaited by a worker once it is this job's
        turn; ``on_start`` (if given) runs right before that, useful for
        flipping a "queued" status message over to "downloading". Raises
        ``QueueFullError`` if the queue is already at capacity.
        """
        if self._queue.full():
            raise QueueFullError(
                f"The queue is full ({self._max_size} requests waiting). "
                "Please try again in a moment."
            )

        job = JobRecord(
            job_id=uuid4().hex,
            chat_id=chat_id,
            user_id=user_id,
            payload=payload,
            created_at=datetime.now().isoformat(),
        )

        # Persist BEFORE enqueuing: once a DB row exists we must guarantee
        # either the handler runs or recover_stale_jobs eventually reports
        # it, never silent loss.
        await asyncio.to_thread(self._insert, job)

        try:
            self._queue.put_nowait((job, handler, on_start))
        except asyncio.QueueFull:
            # Lost a race against another submit(); undo the journal write.
            await asyncio.to_thread(self._delete, job.job_id)
            raise QueueFullError(
                f"The queue is full ({self._max_size} requests waiting). "
                "Please try again in a moment."
            ) from None

        return job

    # =========================================================================
    # Worker loop
    # =========================================================================

    async def _worker_loop(self, name: str) -> None:
        while True:
            job, handler, on_start = await self._queue.get()

            try:
                await asyncio.to_thread(self._mark_processing, job.job_id)

                if on_start is not None:
                    try:
                        await on_start(job)
                    except Exception:
                        logger.exception(
                            "on_start callback failed for job %s", job.job_id
                        )

                coro = handler(job.payload)

                if self._job_timeout:
                    await asyncio.wait_for(coro, timeout=self._job_timeout)
                else:
                    await coro

            except asyncio.CancelledError:
                raise

            except Exception:
                # The handler is expected to report failures to the user
                # itself (see src/bot.py's download()); this is a last-resort
                # net so one bad job can never permanently kill a worker.
                logger.exception(
                    "[%s] Unhandled error running job %s", name, job.job_id
                )

            finally:
                await asyncio.to_thread(self._delete, job.job_id)
                self._queue.task_done()
