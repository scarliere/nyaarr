from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuditLog:
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path

    def append(self, category: str, message: str, anime: dict[str, Any], torrent: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS audit_events(
                sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL, category TEXT NOT NULL, message TEXT NOT NULL,
                anime_library_id TEXT NOT NULL, anime_title TEXT NOT NULL,
                torrent_hash TEXT NOT NULL, torrent_title TEXT NOT NULL, status TEXT NOT NULL)""")
            connection.execute(
                "INSERT INTO audit_events VALUES(NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, datetime.now(timezone.utc).isoformat(), category[:80], message[:4000],
                 str(anime.get("library_id") or ""), str(anime.get("title") or anime.get("original_title") or "")[:500],
                 str(torrent.get("hash") or torrent.get("infohash") or "")[:80], str(torrent.get("title") or "")[:1000],
                 str(torrent.get("status") or "")[:80]),
            )
            connection.commit()

    def rows(self, limit: int) -> list[dict[str, str]]:
        with self._connect() as connection:
            exists = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='audit_events'").fetchone()
            if not exists:
                return []
            rows = connection.execute("SELECT created_at, category, message, anime_title, torrent_title, status FROM audit_events ORDER BY sequence DESC LIMIT ?", (max(1, min(limit, 5000)),)).fetchall()
        return [{"created_at": str(r[0]), "category": str(r[1]), "message": str(r[2]), "anime_title": str(r[3]), "torrent_title": str(r[4]), "status": str(r[5])} for r in rows]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection
