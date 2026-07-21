from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager
from typing import Any, Iterator


_LOCK = threading.RLock()
_SAMPLES: dict[str, deque[tuple[float, bool]]] = {}
_MAX_SAMPLES = 256


def record_timing(name: str, duration_seconds: float, *, ok: bool = True) -> None:
    with _LOCK:
        samples = _SAMPLES.setdefault(name, deque(maxlen=_MAX_SAMPLES))
        samples.append((max(float(duration_seconds), 0.0), bool(ok)))


@contextmanager
def timed(name: str) -> Iterator[None]:
    started = time.perf_counter()
    ok = False
    try:
        yield
        ok = True
    finally:
        record_timing(name, time.perf_counter() - started, ok=ok)


def metrics_snapshot() -> list[dict[str, Any]]:
    with _LOCK:
        copied = {name: list(samples) for name, samples in _SAMPLES.items()}
    rows = []
    for name, samples in sorted(copied.items()):
        if not samples:
            continue
        durations = sorted(duration for duration, _ok in samples)
        percentile_index = min(max(round(0.95 * len(durations) + 0.5) - 1, 0), len(durations) - 1)
        rows.append(
            {
                "name": name,
                "samples": len(samples),
                "failures": sum(1 for _duration, ok in samples if not ok),
                "last_ms": round(samples[-1][0] * 1000, 1),
                "average_ms": round((sum(durations) / len(durations)) * 1000, 1),
                "p95_ms": round(durations[percentile_index] * 1000, 1),
                "max_ms": round(durations[-1] * 1000, 1),
            }
        )
    return rows
