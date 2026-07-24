from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Job:
    job_id: str
    job_type: str
    payload: dict[str, Any]
    idempotency_key: str
    priority: int
    attempts: int


class DurableJobQueue:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        idempotency_key: str,
        priority: int = 50,
        run_after: datetime | None = None,
    ) -> str:
        now = _utc_now()
        due = (run_after or datetime.now(timezone.utc)).isoformat()
        job_id = uuid.uuid4().hex
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT job_id, status FROM jobs WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            if row is None:
                connection.execute(
                    """
                    INSERT INTO jobs(
                        job_id, job_type, payload, idempotency_key, status, priority,
                        attempts, run_after, lease_until, last_error, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, 'pending', ?, 0, ?, '', '', ?, ?)
                    """,
                    (job_id, job_type, json.dumps(payload or {}, sort_keys=True), idempotency_key, priority, due, now, now),
                )
            else:
                job_id = str(row[0])
                if str(row[1]) not in {"pending", "running", "retry"}:
                    connection.execute(
                        """
                        UPDATE jobs
                        SET job_type = ?, payload = ?, status = 'pending', priority = ?,
                            attempts = 0, run_after = ?, lease_until = '', last_error = '', updated_at = ?
                        WHERE job_id = ?
                        """,
                        (job_type, json.dumps(payload or {}, sort_keys=True), priority, due, now, job_id),
                    )
            connection.commit()
        return job_id

    def claim(self, *, lease_seconds: int = 120) -> Job | None:
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "UPDATE jobs SET status = 'retry', lease_until = '', updated_at = ? WHERE status = 'running' AND lease_until < ?",
                (now, now),
            )
            row = connection.execute(
                """
                SELECT job_id, job_type, payload, idempotency_key, priority, attempts
                FROM jobs
                WHERE status IN ('pending', 'retry') AND run_after <= ?
                ORDER BY priority DESC, run_after ASC, created_at ASC
                LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                connection.commit()
                return None
            effective_lease_seconds = 6 * 60 * 60 if str(row[1]) == 'root_scan' else max(lease_seconds, 10)
            lease_until = (now_dt + timedelta(seconds=effective_lease_seconds)).isoformat()
            updated = connection.execute(
                """
                UPDATE jobs
                SET status = 'running', attempts = attempts + 1, lease_until = ?, updated_at = ?
                WHERE job_id = ? AND status IN ('pending', 'retry')
                """,
                (lease_until, now, row[0]),
            ).rowcount
            connection.commit()
        if not updated:
            return None
        try:
            payload = json.loads(str(row[2]))
        except json.JSONDecodeError:
            payload = {}
        return Job(str(row[0]), str(row[1]), payload if isinstance(payload, dict) else {}, str(row[3]), int(row[4]), int(row[5]) + 1)

    def complete(self, job_id: str) -> None:
        self._finish(job_id, "completed", "", None)

    def fail(
        self,
        job_id: str,
        error: str,
        attempts: int,
        *,
        max_attempts: int = 6,
        retry_after_seconds: int | None = None,
    ) -> None:
        if attempts >= max_attempts:
            self._finish(job_id, "failed", error, None)
            return
        delay = (
            max(int(retry_after_seconds), 1)
            if retry_after_seconds is not None
            else min(15 * (2 ** max(attempts - 1, 0)), 30 * 60)
        )
        self._finish(job_id, "retry", error, datetime.now(timezone.utc) + timedelta(seconds=delay))

    def has_active(self, job_type: str, idempotency_key: str | None = None) -> bool:
        query = "SELECT 1 FROM jobs WHERE job_type = ? AND status IN ('pending', 'running', 'retry')"
        parameters: list[Any] = [job_type]
        if idempotency_key:
            query += " AND idempotency_key = ?"
            parameters.append(idempotency_key)
        query += " LIMIT 1"
        with self._connect() as connection:
            return connection.execute(query, parameters).fetchone() is not None

    def summary(self) -> dict[str, Any]:
        now = _utc_now()
        with self._connect() as connection:
            counts = {
                str(status): int(count)
                for status, count in connection.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
            }
            oldest = connection.execute(
                "SELECT created_at FROM jobs WHERE status IN ('pending', 'retry') ORDER BY created_at LIMIT 1"
            ).fetchone()
            failures = connection.execute(
                """
                SELECT job_type, last_error, attempts, updated_at
                FROM jobs WHERE status = 'failed' ORDER BY updated_at DESC LIMIT 5
                """
            ).fetchall()
        return {
            "counts": counts,
            "active": counts.get("pending", 0) + counts.get("running", 0) + counts.get("retry", 0),
            "oldest_pending_at": str(oldest[0]) if oldest else "",
            "checked_at": now,
            "recent_failures": [
                {"job_type": str(row[0]), "error": str(row[1]), "attempts": int(row[2]), "updated_at": str(row[3])}
                for row in failures
            ],
        }

    def reset_non_running(self) -> int:
        """Remove rebuildable queued/history work while leaving active jobs alone."""
        with self._connect() as connection:
            removed = connection.execute("DELETE FROM jobs WHERE status != 'running'").rowcount
            connection.commit()
        return int(removed or 0)

    def prune(self, retain_completed: int = 200) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                DELETE FROM jobs WHERE status = 'completed' AND job_id NOT IN (
                    SELECT job_id FROM jobs WHERE status = 'completed' ORDER BY updated_at DESC LIMIT ?
                )
                """,
                (max(retain_completed, 0),),
            )
            connection.commit()

    def _finish(self, job_id: str, status: str, error: str, run_after: datetime | None) -> None:
        due = (run_after or datetime.now(timezone.utc)).isoformat()
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status = ?, run_after = ?, lease_until = '', last_error = ?, updated_at = ? WHERE job_id = ?",
                (status, due, error[:2000], _utc_now(), job_id),
            )
            connection.commit()

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    job_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    attempts INTEGER NOT NULL,
                    run_after TEXT NOT NULL,
                    lease_until TEXT NOT NULL,
                    last_error TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            connection.execute("CREATE INDEX IF NOT EXISTS jobs_due_idx ON jobs(status, run_after, priority)")
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
