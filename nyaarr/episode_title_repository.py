from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


class SQLiteEpisodeTitleRepository:
    """Persistent best-effort episode titles, isolated from library state."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def upsert(self, records: Iterable[dict[str, Any]]) -> int:
        rows = []
        for record in records:
            mal_id = str(record.get("mal_id") or "").strip()
            episode = _positive_int(record.get("episode"))
            if not mal_id or episode is None:
                continue
            rows.append(
                (
                    mal_id,
                    episode,
                    str(record.get("title") or "").strip(),
                    str(record.get("title_japanese") or "").strip(),
                    str(record.get("title_romanji") or "").strip(),
                    str(record.get("aired_at") or "").strip(),
                    int(bool(record.get("filler"))),
                    int(bool(record.get("recap"))),
                    str(record.get("fetched_at") or _utc_now()),
                )
            )
        if not rows:
            return 0
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO episode_titles(
                    mal_id, episode, title, title_japanese, title_romanji,
                    aired_at, filler, recap, fetched_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(mal_id, episode) DO UPDATE SET
                    title = CASE WHEN excluded.title != '' THEN excluded.title ELSE episode_titles.title END,
                    title_japanese = CASE WHEN excluded.title_japanese != '' THEN excluded.title_japanese ELSE episode_titles.title_japanese END,
                    title_romanji = CASE WHEN excluded.title_romanji != '' THEN excluded.title_romanji ELSE episode_titles.title_romanji END,
                    aired_at = CASE WHEN excluded.aired_at != '' THEN excluded.aired_at ELSE episode_titles.aired_at END,
                    filler = excluded.filler,
                    recap = excluded.recap,
                    fetched_at = excluded.fetched_at
                """,
                rows,
            )
            connection.commit()
        return len(rows)

    def for_anime(self, mal_id: Any) -> list[dict[str, Any]]:
        selected = str(mal_id or "").strip()
        if not selected:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT episode, title, title_japanese, title_romanji,
                       aired_at, filler, recap, fetched_at
                FROM episode_titles
                WHERE mal_id = ?
                ORDER BY episode
                """,
                (selected,),
            ).fetchall()
        return [
            {
                "provider": "jikan",
                "mal_id": selected,
                "episode": int(row[0]),
                "title": str(row[1]),
                "title_japanese": str(row[2]),
                "title_romanji": str(row[3]),
                "aired_at": str(row[4]),
                "filler": bool(row[5]),
                "recap": bool(row[6]),
                "fetched_at": str(row[7]),
            }
            for row in rows
        ]

    def mark_complete(self, mal_id: Any, *, last_visible_page: int, record_count: int) -> None:
        selected = str(mal_id or "").strip()
        if not selected:
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO episode_title_sync(
                    mal_id, last_visible_page, record_count, status, requested_at, checked_at
                )
                VALUES(?, ?, ?, 'complete', ?, ?)
                ON CONFLICT(mal_id) DO UPDATE SET
                    last_visible_page = excluded.last_visible_page,
                    record_count = excluded.record_count,
                    status = excluded.status,
                    requested_at = excluded.requested_at,
                    checked_at = excluded.checked_at
                """,
                (
                    selected,
                    max(int(last_visible_page), 1),
                    max(int(record_count), 0),
                    _utc_now(),
                    _utc_now(),
                ),
            )
            connection.commit()

    def mark_requested(self, mal_id: Any) -> None:
        selected = str(mal_id or "").strip()
        if not selected:
            return
        now = _utc_now()
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO episode_title_sync(
                    mal_id, last_visible_page, record_count, status, requested_at, checked_at
                )
                VALUES(?, 1, 0, 'pending', ?, '')
                ON CONFLICT(mal_id) DO UPDATE SET
                    status = 'pending',
                    requested_at = excluded.requested_at
                """,
                (selected, now),
            )
            connection.commit()

    def checked_at(self, mal_id: Any) -> float | None:
        selected = str(mal_id or "").strip()
        if not selected:
            return None
        with self._connect() as connection:
            row = connection.execute(
                "SELECT checked_at FROM episode_title_sync WHERE mal_id = ?",
                (selected,),
            ).fetchone()
        if not row:
            return None
        try:
            parsed = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()

    def is_pending(self, mal_id: Any, *, max_pending_age_seconds: int = 30 * 60) -> bool:
        selected = str(mal_id or "").strip()
        if not selected:
            return False
        with self._connect() as connection:
            row = connection.execute(
                "SELECT status, requested_at FROM episode_title_sync WHERE mal_id = ?",
                (selected,),
            ).fetchone()
        if not row or str(row[0]) != "pending":
            return False
        try:
            requested_at = datetime.fromisoformat(str(row[1]).replace("Z", "+00:00"))
        except ValueError:
            return False
        if requested_at.tzinfo is None:
            requested_at = requested_at.replace(tzinfo=timezone.utc)
        return (
            datetime.now(timezone.utc).timestamp() - requested_at.timestamp()
            < max(int(max_pending_age_seconds), 1)
        )

    def is_due(self, mal_id: Any, *, max_age_seconds: int, now: float | None = None) -> bool:
        if self.is_pending(mal_id):
            return False
        checked_at = self.checked_at(mal_id)
        if checked_at is None:
            return True
        current = datetime.now(timezone.utc).timestamp() if now is None else now
        return current - checked_at >= max(int(max_age_seconds), 0)

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS episode_titles (
                    mal_id TEXT NOT NULL,
                    episode INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    title_japanese TEXT NOT NULL,
                    title_romanji TEXT NOT NULL,
                    aired_at TEXT NOT NULL,
                    filler INTEGER NOT NULL,
                    recap INTEGER NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(mal_id, episode)
                );
                CREATE INDEX IF NOT EXISTS episode_titles_mal_idx
                    ON episode_titles(mal_id, episode);
                CREATE TABLE IF NOT EXISTS episode_title_sync (
                    mal_id TEXT PRIMARY KEY,
                    last_visible_page INTEGER NOT NULL,
                    record_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    requested_at TEXT NOT NULL,
                    checked_at TEXT NOT NULL
                );
                """
            )
            connection.commit()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
