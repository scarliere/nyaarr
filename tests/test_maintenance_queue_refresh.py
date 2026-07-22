from __future__ import annotations

from nyaarr import app_state, maintenance


def test_default_torrent_search_batch_drains_backlogs_faster() -> None:
    assert app_state.MAX_TORRENT_SEARCHES_PER_TICK == 10


def test_download_queue_refresh_persists_changed_queue(monkeypatch) -> None:
    database = {"anime": [], "settings": {}}
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_refresh_download_queue", lambda state: state is database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda state: writes.append(state))

    summary = app_state.run_download_queue_refresh()

    assert summary["status"] == "ok"
    assert summary["queue_refreshed"] is True
    assert writes == [database]


def test_enqueue_queue_refresh_job_uses_independent_interval(monkeypatch) -> None:
    jobs = []

    monkeypatch.setattr(app_state, "DOWNLOAD_QUEUE_REFRESH_INTERVAL_SECONDS", 5)
    monkeypatch.setattr(maintenance.time, "time", lambda: 100.0)
    monkeypatch.setattr(maintenance, "has_active_job", lambda job_type: False)
    monkeypatch.setattr(
        maintenance,
        "enqueue_job",
        lambda job_type, **kwargs: jobs.append((job_type, kwargs)) or "job",
    )

    maintenance._enqueue_queue_refresh_job()

    assert jobs == [
        (
            "download_queue_refresh",
            {"idempotency_key": "download-queue-refresh:20", "priority": 95},
        )
    ]
