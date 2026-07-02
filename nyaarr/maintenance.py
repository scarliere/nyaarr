from __future__ import annotations

import atexit
import os
import sys
import threading

from .app_state import (
    PERIODIC_MAINTENANCE_INTERVAL_SECONDS,
    run_periodic_maintenance_tick,
    run_startup_download_status_check,
)


_INITIAL_DELAY_SECONDS = int(os.environ.get("NYAARR_PERIODIC_INITIAL_DELAY_SECONDS", "5"))
_started = False
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def start_periodic_maintenance() -> None:
    global _started, _thread
    if _started or os.environ.get("NYAARR_DISABLE_PERIODIC_MAINTENANCE") == "1":
        return

    _started = True
    _thread = threading.Thread(target=_maintenance_loop, name="nyaarr-maintenance", daemon=True)
    _thread.start()
    atexit.register(stop_periodic_maintenance)


def stop_periodic_maintenance() -> None:
    _stop_event.set()


def _maintenance_loop() -> None:
    try:
        run_startup_download_status_check()
    except Exception as exc:  # pragma: no cover - defensive background guard
        print(f"Nyaarr startup torrent status check failed: {exc}", file=sys.stderr)

    delay = max(_INITIAL_DELAY_SECONDS, 0)
    while not _stop_event.wait(delay):
        try:
            run_periodic_maintenance_tick(include_airing=True)
        except Exception as exc:  # pragma: no cover - defensive background guard
            print(f"Nyaarr periodic maintenance failed: {exc}", file=sys.stderr)
        delay = max(PERIODIC_MAINTENANCE_INTERVAL_SECONDS, 5)
