from __future__ import annotations

import copy
import json
import os
import shutil
import sqlite3
import threading
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


REVISION_FIELD = "__nyaarr_storage_revision"
# Complete snapshots are expensive for large libraries; eight still cover normal concurrent writes.
_HISTORY_LIMIT = 8


class StateRepositoryError(RuntimeError):
    """Raised when durable application state cannot be read or committed."""


class SQLiteStateRepository:
    """Versioned single-document repository with a JSON compatibility mirror.

    Nyaarr still has a document-shaped domain model. Keeping that model behind a
    repository lets services be split without requiring a risky all-at-once data
    rewrite. SQLite supplies process-safe transactions and WAL readers; the JSON
    mirror remains available to existing backup and recovery workflows.
    """

    def __init__(self, json_path: Path, initial_factory: Callable[[], dict[str, Any]]) -> None:
        self.json_path = json_path
        configured = os.environ.get("NYAARR_STATE_DATABASE_PATH", "").strip()
        self.database_path = Path(configured) if configured else json_path.with_suffix(".sqlite3")
        self.initial_factory = initial_factory
        self._lock = threading.RLock()
        self._history: OrderedDict[int, dict[str, Any]] = OrderedDict()

    def read(self) -> dict[str, Any]:
        with self._lock:
            self._initialize()
            with self._connect() as connection:
                row = connection.execute("SELECT revision, document FROM app_state WHERE id = 1").fetchone()
            if row is None:
                raise StateRepositoryError("Application state was not initialized.")
            revision, document = int(row[0]), str(row[1])
            try:
                state = json.loads(document)
            except json.JSONDecodeError as exc:
                raise StateRepositoryError(f"Stored application state is invalid JSON: {exc}.") from exc
            if not isinstance(state, dict):
                raise StateRepositoryError("Stored application state is not an object.")
            self._remember(revision, state)
            result = copy.deepcopy(state)
            result[REVISION_FIELD] = revision
            return result

    def write(self, proposed: dict[str, Any]) -> dict[str, Any]:
        clean_proposed = _without_repository_fields(proposed)
        proposed_revision = _revision_value(proposed.get(REVISION_FIELD))
        with self._lock:
            self._initialize()
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute("SELECT revision, document FROM app_state WHERE id = 1").fetchone()
                if row is None:
                    connection.rollback()
                    raise StateRepositoryError("Application state was not initialized.")
                current_revision = int(row[0])
                latest = json.loads(str(row[1]))
                if proposed_revision is None or proposed_revision == current_revision:
                    committed = clean_proposed
                else:
                    base = self._history.get(proposed_revision)
                    if base is None:
                        connection.rollback()
                        raise StateRepositoryError(
                            f'Stale state revision {proposed_revision} is no longer available; reload and retry.'
                        )
                    committed = _three_way_merge(base, clean_proposed, latest)
                next_revision = current_revision + 1
                serialized = _serialize(committed)
                connection.execute(
                    "UPDATE app_state SET revision = ?, document = ?, updated_at = ? WHERE id = 1",
                    (next_revision, serialized, _utc_now()),
                )
                connection.commit()
            self._remember(next_revision, committed)
            self._write_json_mirror(serialized)
            proposed.clear()
            proposed.update(copy.deepcopy(committed))
            proposed[REVISION_FIELD] = next_revision
            return proposed

    def revision(self) -> int:
        with self._lock:
            self._initialize()
            with self._connect() as connection:
                row = connection.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            return int(row[0]) if row else 0

    def _initialize(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS app_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    revision INTEGER NOT NULL,
                    document TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            row = connection.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            if row is not None:
                return
            state = self._load_initial_state()
            serialized = _serialize(state)
            connection.execute(
                "INSERT INTO app_state(id, revision, document, updated_at) VALUES(1, 1, ?, ?)",
                (serialized, _utc_now()),
            )
            connection.commit()
            self._remember(1, state)
            self._write_json_mirror(serialized)

    def _load_initial_state(self) -> dict[str, Any]:
        if self.json_path.exists():
            try:
                loaded = json.loads(self.json_path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._backup_legacy_json()
                    return _without_repository_fields(loaded)
            except (OSError, json.JSONDecodeError):
                pass
        return _without_repository_fields(self.initial_factory())

    def _backup_legacy_json(self) -> None:
        backup_path = self.json_path.with_suffix(".pre-sqlite.json")
        if backup_path.exists():
            return
        try:
            shutil.copy2(self.json_path, backup_path)
        except OSError:
            return

    def _write_json_mirror(self, serialized: str) -> None:
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.json_path.with_suffix(".json.tmp")
        temp_path.write_text(serialized, encoding="utf-8")
        os.replace(temp_path, self.json_path)
        try:
            os.chmod(self.json_path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _remember(self, revision: int, state: dict[str, Any]) -> None:
        self._history[revision] = copy.deepcopy(_without_repository_fields(state))
        self._history.move_to_end(revision)
        while len(self._history) > _HISTORY_LIMIT:
            self._history.popitem(last=False)


def _three_way_merge(base: Any, proposed: Any, latest: Any) -> Any:
    if proposed == base:
        return copy.deepcopy(latest)
    if isinstance(base, dict) and isinstance(proposed, dict) and isinstance(latest, dict):
        merged = copy.deepcopy(latest)
        for key in base.keys() - proposed.keys():
            merged.pop(key, None)
        for key, proposed_value in proposed.items():
            if key == REVISION_FIELD:
                continue
            if key not in base:
                merged[key] = copy.deepcopy(proposed_value)
                continue
            merged[key] = _three_way_merge(base[key], proposed_value, latest.get(key))
        return merged
    if isinstance(base, list) and isinstance(proposed, list) and isinstance(latest, list):
        return _merge_lists(base, proposed, latest)
    return copy.deepcopy(proposed)


def _merge_lists(base: list[Any], proposed: list[Any], latest: list[Any]) -> list[Any]:
    identity_key = _list_identity_key(base, proposed, latest)
    if identity_key is None:
        return copy.deepcopy(proposed)
    base_map = {_item_identity(item, identity_key): item for item in base}
    proposed_map = {_item_identity(item, identity_key): item for item in proposed}
    latest_map = {_item_identity(item, identity_key): item for item in latest}
    removed = base_map.keys() - proposed_map.keys()
    result: list[Any] = []
    seen: set[str] = set()
    for item in latest:
        identity = _item_identity(item, identity_key)
        if identity in removed:
            continue
        if identity in proposed_map and identity in base_map:
            result.append(_three_way_merge(base_map[identity], proposed_map[identity], item))
        else:
            result.append(copy.deepcopy(item))
        seen.add(identity)
    for item in proposed:
        identity = _item_identity(item, identity_key)
        if identity not in seen:
            result.append(copy.deepcopy(item))
            seen.add(identity)
    return result


def _list_identity_key(*lists: list[Any]) -> str | None:
    items = [item for values in lists for item in values if isinstance(item, dict)]
    if not items:
        return None
    for key in ("library_id", "ignore_key", "job_id", "hash", "infohash", "selection_key", "created_at"):
        if all(str(item.get(key) or "").strip() for item in items):
            return key
    return None


def _item_identity(item: Any, key: str) -> str:
    if not isinstance(item, dict):
        return json.dumps(item, sort_keys=True, default=str)
    value = str(item.get(key) or "").strip().casefold()
    if key == "created_at":
        value += "|" + str(item.get("message") or "")
    return value


def _without_repository_fields(state: dict[str, Any]) -> dict[str, Any]:
    clean = copy.deepcopy(state)
    clean.pop(REVISION_FIELD, None)
    return clean


def _revision_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize(state: dict[str, Any]) -> str:
    return json.dumps(_without_repository_fields(state), indent=2, sort_keys=True) + "\n"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
