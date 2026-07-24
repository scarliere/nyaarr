from pathlib import Path

from nyaarr import app_state, job_queue, maintenance


class FakeRepository:
    def __init__(self, database_path: Path):
        self.database_path = database_path
        self.history_cleared = False

    def backup(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"sqlite backup")
        return destination

    def clear_history(self) -> None:
        self.history_cleared = True


def test_stale_reset_requires_exact_confirmation(monkeypatch):
    monkeypatch.setattr(app_state, "_read_user_database", lambda: (_ for _ in ()).throw(AssertionError("must not read")))
    success, message = app_state.hard_reset_stale_application_state("reset")
    assert success is False
    assert "RESET" in message


def test_stale_reset_backs_up_and_preserves_user_and_media_state(monkeypatch, tmp_path):
    media = tmp_path / "Anime" / "Show" / "episode-01.mkv"
    media.parent.mkdir(parents=True)
    media.write_bytes(b"media")
    queue = {"hash": "abc", "status": "downloading", "content_path": str(media)}
    database = {
        "settings": {"root_folder": str(tmp_path / "Anime"), "download_client": {"enabled": True}},
        "auth": {"superadmin": {"username": "owner", "password_hash": "hash"}},
        "issues": [{"issue_key": "stale", "status": "open"}],
        "events": [],
        "anime": [{
            "library_id": "anime-1", "title": "Show", "monitored": True,
            "local_path": str(media.parent), "episode_files": [str(media)],
            "download_queues": [queue], "download_queue": queue,
            "completion": {"expected_episodes": 2, "local_episodes": 1, "missing_episodes": 1},
            "torrent_search": {"candidates": [{"title": "stale"}], "checked_at": "old"},
            "torrent_manual_selection": {"required": True}, "automation": {"exhaustive_cycles": 3},
        }],
    }
    writes = []
    enqueued = []
    repository = FakeRepository(tmp_path / "state.sqlite3")
    monkeypatch.setattr(app_state, "STATE_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(app_state, "RESOLVED_METADATA_CACHE_PATH", tmp_path / "resolved.json")
    monkeypatch.setattr(app_state.metadata_module, "OFFLINE_CACHE_FILE", tmp_path / "offline.json")
    monkeypatch.setattr(app_state.metadata_module, "OFFLINE_CACHE_METADATA_FILE", tmp_path / "offline-meta.json")
    monkeypatch.setattr(app_state.metadata_module, "clear_runtime_caches", lambda: None)
    monkeypatch.setattr(app_state.torrent_finder_module, "clear_runtime_caches", lambda: None)
    monkeypatch.setattr(app_state, "_state_repository", lambda: repository)
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda value: writes.append(value))
    monkeypatch.setattr(app_state, "_record_event", lambda *args, **kwargs: None)
    monkeypatch.setattr(job_queue.DurableJobQueue, "reset_non_running", lambda self: 4)
    monkeypatch.setattr(maintenance, "begin_recovery_barrier", lambda: True)
    monkeypatch.setattr(maintenance, "end_recovery_barrier", lambda: None)
    monkeypatch.setattr(maintenance, "enqueue_job", lambda job_type, payload=None, **kwargs: enqueued.append((job_type, payload)))

    success, message = app_state.hard_reset_stale_application_state("RESET")

    assert success is True
    assert "Backup:" in message
    assert list((tmp_path / "backups").glob("nyaarr-state-*.sqlite3"))
    assert repository.history_cleared is True
    assert writes == [database]
    assert database["settings"]["root_folder"] == str(tmp_path / "Anime")
    assert database["auth"]["superadmin"]["username"] == "owner"
    assert database["anime"][0]["episode_files"] == [str(media)]
    assert database["anime"][0]["download_queues"] == [queue]
    assert database["anime"][0]["torrent_search"]["candidates"] == []
    assert database["anime"][0]["torrent_manual_selection"] == {"required": False}
    assert "automation" not in database["anime"][0]
    assert database["issues"] == []
    assert media.read_bytes() == b"media"
    assert {item[0] for item in enqueued} == {"startup_reconcile", "local_reconcile", "external_refresh", "anilist_refresh", "offline_metadata_refresh", "root_scan"}

