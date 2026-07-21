from __future__ import annotations

import json
import threading

from nyaarr import metadata, qbittorrent_client, torrent_finder
from nyaarr.job_queue import DurableJobQueue
from nyaarr.persistence import SQLiteStateRepository
from nyaarr.metrics import metrics_snapshot, record_timing


def _initial_state() -> dict[str, object]:
    return {
        "schema_version": 1,
        "settings": {},
        "events": [],
        "anime": [
            {"library_id": "anime-a", "title": "A", "monitored": True},
            {"library_id": "anime-b", "title": "B", "monitored": True},
        ],
    }


def test_sqlite_repository_migrates_json_and_merges_stale_independent_updates(tmp_path) -> None:
    json_path = tmp_path / "anime-library.json"
    json_path.write_text(json.dumps(_initial_state()), encoding="utf-8")
    repository = SQLiteStateRepository(json_path, _initial_state)

    first = repository.read()
    stale = repository.read()
    first["anime"][0]["title"] = "A updated"
    repository.write(first)
    stale["anime"][1]["title"] = "B updated"
    repository.write(stale)

    current = repository.read()
    assert [anime["title"] for anime in current["anime"]] == ["A updated", "B updated"]
    assert json.loads(json_path.read_text(encoding="utf-8"))["anime"][0]["title"] == "A updated"
    assert json_path.with_suffix(".pre-sqlite.json").exists()


def test_durable_jobs_deduplicate_and_retry_with_backoff(tmp_path) -> None:
    queue = DurableJobQueue(tmp_path / "state.sqlite3")
    first_id = queue.enqueue("search", {"query": "anime"}, idempotency_key="search:anime")
    second_id = queue.enqueue("search", {"query": "anime"}, idempotency_key="search:anime")

    assert second_id == first_id
    job = queue.claim()
    assert job is not None
    assert job.payload == {"query": "anime"}
    queue.fail(job.job_id, "provider unavailable", job.attempts)
    summary = queue.summary()
    assert summary["counts"]["retry"] == 1


def test_durable_jobs_claim_user_priority_before_background_repairs(tmp_path) -> None:
    queue = DurableJobQueue(tmp_path / 'state.sqlite3')
    queue.enqueue('poster', idempotency_key='poster:1', priority=10)
    queue.enqueue('root_scan', idempotency_key='root:1', priority=95)

    job = queue.claim()

    assert job is not None
    assert job.job_type == 'root_scan'


def test_latency_metrics_are_bounded_and_report_failures() -> None:
    for index in range(300):
        record_timing('test.operation', index / 1000, ok=index % 10 != 0)

    metric = next(row for row in metrics_snapshot() if row['name'] == 'test.operation')

    assert metric['samples'] == 256
    assert metric['failures'] > 0
    assert metric['p95_ms'] <= metric['max_ms']


def test_completed_job_can_be_scheduled_again_with_same_idempotency_key(tmp_path) -> None:
    queue = DurableJobQueue(tmp_path / "state.sqlite3")
    job_id = queue.enqueue("reconcile", idempotency_key="reconcile:1")
    job = queue.claim()
    assert job is not None
    queue.complete(job.job_id)

    assert queue.enqueue("reconcile", idempotency_key="reconcile:1") == job_id
    assert queue.claim() is not None


def test_interactive_offline_metadata_lookup_never_starts_cache_download(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(metadata, "OFFLINE_DATABASE_PATHS", (tmp_path / "missing.json",))
    monkeypatch.delenv("ANIME_OFFLINE_DATABASE_PATH", raising=False)
    monkeypatch.setattr(
        metadata,
        "_ensure_offline_database_cache",
        lambda: (_ for _ in ()).throw(AssertionError("interactive lookup must not download")),
    )

    assert metadata._offline_database_path() is None


def test_qbittorrent_factory_reuses_authenticated_session(monkeypatch) -> None:
    created = []

    class FakeClient:
        def __init__(self, settings, timeout=10):
            self.settings = settings
            self.timeout = timeout
            self.logins = 0
            created.append(self)

        def login(self):
            self.logins += 1

    settings = {
        "download_client": {
            "implementation": "qbittorrent",
            "enabled": True,
            "host": "127.0.0.1",
            "port": 8080,
        }
    }
    qbittorrent_client.clear_client_cache()
    monkeypatch.setattr(qbittorrent_client, "QBittorrentClient", FakeClient)

    first = qbittorrent_client.client_from_settings(settings)
    second = qbittorrent_client.client_from_settings(settings)

    assert first is second
    assert len(created) == 1
    assert created[0].logins == 1


def test_identical_nyaa_requests_share_one_inflight_fetch(monkeypatch) -> None:
    calls = []
    release = {"title": "[Group] Anime - 01 [1080p]", "infohash": "abc"}
    started = threading.Event()
    release_fetch = threading.Event()

    def fetch(query):
        calls.append(query)
        started.set()
        assert release_fetch.wait(timeout=2)
        return [release]

    torrent_finder._RSS_CACHE.clear()
    torrent_finder._RSS_INFLIGHT.clear()
    monkeypatch.setattr(torrent_finder, "_fetch_nyaa_rss", fetch)

    results = []
    first = threading.Thread(target=lambda: results.append(torrent_finder.search_nyaa_rss("Anime")))
    second = threading.Thread(target=lambda: results.append(torrent_finder.search_nyaa_rss("Anime")))
    first.start()
    assert started.wait(timeout=2)
    second.start()
    release_fetch.set()
    first.join(timeout=3)
    second.join(timeout=3)

    assert len(calls) == 1
    assert results == [[release], [release]]
