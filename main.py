import os
import sys
from pathlib import Path

from nyaarr import create_app
from nyaarr.single_instance import SingleInstanceError, SingleInstanceLock


_instance_lock: SingleInstanceLock | None = None


def _lock_path() -> Path:
    return Path(os.environ.get("NYAARR_INSTANCE_LOCK_PATH", "data/user/nyaarr.lock"))


def _create_locked_app():
    global _instance_lock
    if os.environ.get("NYAARR_DISABLE_INSTANCE_LOCK") != "1":
        _instance_lock = SingleInstanceLock(_lock_path())
        _instance_lock.acquire()
    return create_app()


try:
    app = _create_locked_app()
except SingleInstanceError as exc:
    print(f"Nyaarr is already running: {exc}", file=sys.stderr)
    raise SystemExit(2) from exc


if __name__ == "__main__":
    host = os.environ.get("NYAARR_HOST", "127.0.0.1")
    port = int(os.environ.get("NYAARR_PORT", "1269"))
    debug = os.environ.get("NYAARR_DEBUG", "0") == "1"
    if debug:
        app.run(host=host, port=port, debug=True, use_reloader=False)
    else:
        from waitress import serve

        threads = max(int(os.environ.get("NYAARR_WEB_THREADS", "8")), 2)
        serve(app, host=host, port=port, threads=threads)
