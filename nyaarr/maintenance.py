from __future__ import annotations

import atexit
import concurrent.futures
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import app_state
from .job_queue import DurableJobQueue, Job
from .metadata import refresh_offline_database_cache
from .metrics import timed


_INITIAL_DELAY_SECONDS = int(os.environ.get("NYAARR_PERIODIC_INITIAL_DELAY_SECONDS", "5"))
_WORKER_COUNT = min(8, max(1, int(os.environ.get("NYAARR_JOB_WORKERS", "4"))))
_started = False
_stop_event = threading.Event()
_thread: threading.Thread | None = None
_executor: concurrent.futures.ThreadPoolExecutor | None = None
_active_futures: dict[concurrent.futures.Future[Any], Job] = {}
_scheduler_lock = threading.RLock()


def start_periodic_maintenance() -> None:
    global _started, _thread, _executor
    if _started or os.environ.get("NYAARR_DISABLE_PERIODIC_MAINTENANCE") == "1":
        return
    _started = True
    _stop_event.clear()
    _executor = concurrent.futures.ThreadPoolExecutor(max_workers=_WORKER_COUNT, thread_name_prefix="nyaarr-job")
    _thread = threading.Thread(target=_scheduler_loop, name="nyaarr-scheduler", daemon=True)
    _thread.start()
    atexit.register(stop_periodic_maintenance)


def stop_periodic_maintenance() -> None:
    global _executor
    _stop_event.set()
    executor = _executor
    _executor = None
    if executor is not None:
        executor.shutdown(wait=False, cancel_futures=False)


def enqueue_job(
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    idempotency_key: str,
    priority: int = 50,
    run_after: datetime | None = None,
) -> str:
    return _job_queue().enqueue(
        job_type,
        payload,
        idempotency_key=idempotency_key,
        priority=priority,
        run_after=run_after,
    )


def job_status_summary() -> dict[str, Any]:
    try:
        return _job_queue().summary()
    except Exception as exc:
        return {"counts": {}, "active": 0, "oldest_pending_at": "", "recent_failures": [], "error": str(exc)}


def has_active_job(job_type: str, idempotency_key: str | None = None) -> bool:
    try:
        return _job_queue().has_active(job_type, idempotency_key)
    except Exception:
        return False


def _scheduler_loop() -> None:
    next_periodic = time.monotonic() + max(_INITIAL_DELAY_SECONDS, 0)
    startup_queued = False
    while not _stop_event.wait(0.5):
        try:
            if not startup_queued:
                enqueue_job("startup_reconcile", idempotency_key="startup-reconcile", priority=100)
                startup_queued = True
            now = time.monotonic()
            if now >= next_periodic:
                _enqueue_periodic_jobs()
                next_periodic = now + max(app_state.PERIODIC_MAINTENANCE_INTERVAL_SECONDS, 5)
            _collect_finished_jobs()
            _dispatch_due_jobs()
        except Exception as exc:  # pragma: no cover - defensive scheduler guard
            print(f"Nyaarr scheduler failed: {exc}", file=sys.stderr)


def _enqueue_periodic_jobs() -> None:
    generation = int(time.time() // max(app_state.PERIODIC_MAINTENANCE_INTERVAL_SECONDS, 5))
    if not has_active_job('local_reconcile'):
        enqueue_job("local_reconcile", idempotency_key=f"local-reconcile:{generation}", priority=90)
    if not has_active_job('external_refresh'):
        enqueue_job("external_refresh", idempotency_key=f"external-refresh:{generation}", priority=40)
    if not has_active_job('anilist_refresh'):
        enqueue_job("anilist_refresh", idempotency_key=f"anilist-refresh:{generation}", priority=30)
    day_generation = datetime.now(timezone.utc).date().isoformat()
    if not has_active_job('offline_metadata_refresh'):
        enqueue_job("offline_metadata_refresh", idempotency_key=f"offline-metadata:{day_generation}", priority=10)


def _dispatch_due_jobs() -> None:
    executor = _executor
    if executor is None:
        return
    with _scheduler_lock:
        available = _WORKER_COUNT - len(_active_futures)
        for _ in range(max(available, 0)):
            job = _job_queue().claim(lease_seconds=10 * 60)
            if job is None:
                break
            future = executor.submit(_run_job, job)
            _active_futures[future] = job


def _collect_finished_jobs() -> None:
    with _scheduler_lock:
        finished = [future for future in _active_futures if future.done()]
        for future in finished:
            job = _active_futures.pop(future)
            try:
                future.result()
            except Exception as exc:  # pragma: no cover - exercised through queue state
                retry_after = getattr(exc, "retry_after", None)
                _job_queue().fail(
                    job.job_id,
                    str(exc),
                    job.attempts,
                    retry_after_seconds=int(retry_after) if retry_after is not None else None,
                )
                print(f"Nyaarr job {job.job_type} failed: {exc}", file=sys.stderr)
            else:
                _job_queue().complete(job.job_id)
        if finished:
            _job_queue().prune()


def _run_job(job: Job) -> None:
    handlers: dict[str, Callable[[dict[str, Any]], None]] = {
        "startup_reconcile": _run_startup_reconcile,
        "local_reconcile": _run_local_reconcile,
        "external_refresh": _run_external_refresh,
        "airing_refresh": _run_airing_refresh,
        "anilist_refresh": _run_anilist_refresh,
        "calendar_airing_window": _run_calendar_airing_window,
        "jikan_episode_titles": _run_jikan_episode_titles,
        "root_scan": _run_root_scan,
        "offline_metadata_refresh": _run_offline_metadata_refresh,
    }
    handler = handlers.get(job.job_type)
    if handler is None:
        raise RuntimeError(f"Unknown maintenance job type: {job.job_type}")
    with timed(f'job.{job.job_type}'):
        handler(job.payload)


def _run_startup_reconcile(_payload: dict[str, Any]) -> None:
    app_state.run_startup_download_status_check()


def _run_local_reconcile(_payload: dict[str, Any]) -> None:
    app_state.run_periodic_maintenance_tick(include_airing=False, include_external=False, include_local=True)


def _run_external_refresh(_payload: dict[str, Any]) -> None:
    app_state.run_periodic_maintenance_tick(include_airing=False, include_external=True, include_local=False)


def _run_airing_refresh(_payload: dict[str, Any]) -> None:
    app_state.refresh_library_airing_schedule(force=False, max_checked=app_state.MAX_AIRING_REFRESHES_PER_TICK)


def _run_anilist_refresh(_payload: dict[str, Any]) -> None:
    app_state.refresh_library_anilist_state(force=False, max_checked=app_state.MAX_AIRING_REFRESHES_PER_TICK)


def _run_calendar_airing_window(payload: dict[str, Any]) -> None:
    app_state.hydrate_calendar_airing_window(payload)


def _run_jikan_episode_titles(payload: dict[str, Any]) -> None:
    app_state.hydrate_jikan_episode_titles(payload)


def _run_root_scan(payload: dict[str, Any]) -> None:
    root_folder = str(payload.get("root_folder") or "").strip()
    if not root_folder:
        raise RuntimeError("Root scan job is missing its root folder.")
    app_state._run_root_folder_scan_job(Path(root_folder))
    progress = app_state.root_folder_scan_progress()
    if str(progress.get('phase') or '').casefold() == 'failed':
        raise RuntimeError(str(progress.get('message') or 'Root folder scan failed.'))


def _run_offline_metadata_refresh(_payload: dict[str, Any]) -> None:
    refresh_offline_database_cache()


def _job_queue() -> DurableJobQueue:
    return DurableJobQueue(app_state._state_repository().database_path)
