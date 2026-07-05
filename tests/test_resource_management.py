from __future__ import annotations

from pathlib import Path

from nyaarr import app_state, torrent_finder
from nyaarr.single_instance import SingleInstanceError, SingleInstanceLock


def test_prune_user_database_caps_ignored_torrents_and_queue_history(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "MAX_IGNORED_TORRENTS", 2)
    monkeypatch.setattr(app_state, "MAX_QUEUE_HISTORY_PER_ANIME", 2)
    monkeypatch.setattr(app_state, "MAX_METADATA_CANDIDATES_PER_ANIME", 2)
    monkeypatch.setattr(app_state, "MAX_FLAGGED_FILES_PER_QUEUE", 1)
    monkeypatch.setattr(app_state, "MAX_SELECTED_FILES_PER_QUEUE", 1)
    database = {
        "ignored_torrents": [
            {"key": "old", "ignored_at": "2026-01-01T00:00:00+00:00"},
            {"key": "new", "ignored_at": "2026-01-03T00:00:00+00:00"},
            {"key": "mid", "ignored_at": "2026-01-02T00:00:00+00:00"},
        ],
        "anime": [
            {
                "metadata_candidates": [{"id": 1}, {"id": 2}, {"id": 3}],
                "download_queues": [
                    {"status": "completed", "completed_at": "2026-01-01T00:00:00+00:00"},
                    {"status": "rejected", "rejected_at": "2026-01-02T00:00:00+00:00"},
                    {"status": "imported", "completed_at": "2026-01-03T00:00:00+00:00"},
                    {
                        "status": "queued",
                        "flagged_files": [{"name": "one.exe"}, {"name": "two.exe"}],
                        "selected_episode_files": [{"episode": 1}, {"episode": 2}],
                    },
                ],
            }
        ],
    }

    assert app_state._prune_user_database(database) is True

    assert [item["key"] for item in database["ignored_torrents"]] == ["mid", "new"]
    anime = database["anime"][0]
    assert anime["metadata_candidates"] == [{"id": 1}, {"id": 2}]
    assert [queue["status"] for queue in anime["download_queues"]] == ["rejected", "imported", "queued"]
    assert anime["download_queue"]["status"] == "queued"
    assert anime["download_queue"]["flagged_files"] == [{"name": "one.exe"}]
    assert anime["download_queue"]["selected_episode_files"] == [{"episode": 1}]


def test_prune_resolved_metadata_cache_keeps_latest_entries(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "MAX_RESOLVED_METADATA_CACHE_ENTRIES", 2)
    cache = {"resolved": {"one": {}, "two": {}, "three": {}}}

    assert app_state._prune_resolved_metadata_cache(cache) is True

    assert list(cache["resolved"]) == ["two", "three"]


def test_rss_cache_prune_removes_expired_and_oldest(monkeypatch) -> None:
    monkeypatch.setattr(torrent_finder, "NYAA_RSS_CACHE_TTL_SECONDS", 10)
    monkeypatch.setattr(torrent_finder, "NYAA_RSS_CACHE_MAX_ENTRIES", 2)
    torrent_finder._RSS_CACHE.clear()
    torrent_finder._RSS_CACHE.update(
        {
            "expired": (80.0, []),
            "old": (95.0, []),
            "new": (99.0, []),
            "newer": (100.0, []),
        }
    )

    with torrent_finder._RSS_CACHE_LOCK:
        torrent_finder._prune_rss_cache_locked(100.0)

    assert list(torrent_finder._RSS_CACHE) == ["new", "newer"]


def test_single_instance_lock_rejects_second_holder(tmp_path: Path) -> None:
    first = SingleInstanceLock(tmp_path / "nyaarr.lock")
    second = SingleInstanceLock(tmp_path / "nyaarr.lock")
    first.acquire()
    try:
        try:
            second.acquire()
        except SingleInstanceError:
            blocked = True
        else:
            blocked = False
    finally:
        second.release()
        first.release()

    assert blocked is True
