from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


class SQLiteAiringRepository:
    """Indexed episode-airing cache kept out of the main library document."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path
        self._initialize()

    def upsert(self, records: Iterable[dict[str, Any]]) -> int:
        rows = []
        now = _utc_now()
        for record in records:
            media_id = str(record.get("media_id") or "").strip()
            episode = _positive_int(record.get("episode"))
            airing_at = str(record.get("airing_at") or "").strip()
            if not media_id or episode is None or not airing_at:
                continue
            rows.append((
                str(record.get("provider") or "anilist").strip().casefold(),
                media_id, episode, airing_at,
                "exact" if record.get("precision") == "exact" else "estimated",
                str(record.get("inference_source") or ""),
                str(record.get("fetched_at") or now),
            ))
        if not rows:
            return 0
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO anime_airings(
                    provider, media_id, episode, airing_at, precision,
                    inference_source, fetched_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, media_id, episode) DO UPDATE SET
                    airing_at = excluded.airing_at,
                    precision = excluded.precision,
                    inference_source = excluded.inference_source,
                    fetched_at = excluded.fetched_at
                WHERE anime_airings.precision != 'exact' OR excluded.precision = 'exact'
                """, rows,
            )
            connection.commit()
        return len(rows)

    def for_media(self, media_id: Any, *, provider: str = "anilist") -> list[dict[str, Any]]:
        selected = str(media_id or "").strip()
        if not selected:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT episode, airing_at, precision, inference_source, fetched_at
                FROM anime_airings
                WHERE provider = ? AND media_id = ?
                ORDER BY episode
                """, (provider.casefold(), selected),
            ).fetchall()
        return [
            {
                "provider": provider.casefold(), "media_id": selected,
                "episode": int(row[0]), "airing_at": str(row[1]),
                "precision": str(row[2]), "inference_source": str(row[3]),
                "fetched_at": str(row[4]),
            }
            for row in rows
        ]

    def for_range(
        self, media_ids: Iterable[Any], start_at: str, end_at: str, *,
        provider: str = "anilist",
    ) -> list[dict[str, Any]]:
        selected = sorted({str(value).strip() for value in media_ids if str(value or "").strip()})
        if not selected:
            return []
        placeholders = ",".join("?" for _ in selected)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT media_id, episode, airing_at, precision, inference_source, fetched_at
                FROM anime_airings
                WHERE provider = ? AND media_id IN ({placeholders})
                  AND airing_at >= ? AND airing_at < ?
                ORDER BY airing_at, media_id, episode
                """, (provider.casefold(), *selected, start_at, end_at),
            ).fetchall()
        return [
            {
                "provider": provider.casefold(), "media_id": str(row[0]),
                "episode": int(row[1]), "airing_at": str(row[2]),
                "precision": str(row[3]), "inference_source": str(row[4]),
                "fetched_at": str(row[5]),
            }
            for row in rows
        ]

    def missing_coverage(
        self, media_ids: Iterable[Any], utc_month: str, *,
        max_age_days: int = 30, provider: str = "anilist",
    ) -> list[str]:
        selected = sorted({str(value).strip() for value in media_ids if str(value or "").strip()})
        if not selected:
            return []
        threshold = (
            datetime.now(timezone.utc) - timedelta(days=max(max_age_days, 0))
        ).isoformat().replace("+00:00", "Z")
        placeholders = ",".join("?" for _ in selected)
        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT media_id FROM airing_coverage
                WHERE provider = ? AND utc_month = ? AND media_id IN ({placeholders})
                  AND fetched_at >= ?
                """, (provider.casefold(), utc_month, *selected, threshold),
            ).fetchall()
        covered = {str(row[0]) for row in rows}
        return [media_id for media_id in selected if media_id not in covered]

    def mark_coverage(
        self, media_ids: Iterable[Any], utc_month: str, *,
        provider: str = "anilist",
    ) -> None:
        now = _utc_now()
        rows = [
            (provider.casefold(), str(media_id).strip(), utc_month, now)
            for media_id in media_ids if str(media_id or "").strip()
        ]
        if not rows:
            return
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO airing_coverage(provider, media_id, utc_month, fetched_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(provider, media_id, utc_month) DO UPDATE SET fetched_at = excluded.fetched_at
                """, rows,
            )
            connection.commit()

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS anime_airings (
                    provider TEXT NOT NULL,
                    media_id TEXT NOT NULL,
                    episode INTEGER NOT NULL,
                    airing_at TEXT NOT NULL,
                    precision TEXT NOT NULL,
                    inference_source TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(provider, media_id, episode)
                );
                CREATE INDEX IF NOT EXISTS anime_airings_time_idx
                    ON anime_airings(airing_at, provider, media_id);
                CREATE TABLE IF NOT EXISTS airing_coverage (
                    provider TEXT NOT NULL,
                    media_id TEXT NOT NULL,
                    utc_month TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY(provider, media_id, utc_month)
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
