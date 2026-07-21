from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nyaarr import app_state, maintenance, metadata
from nyaarr.airing_repository import SQLiteAiringRepository


def airing(media_id: str, episode: int, timestamp: str, precision: str = "exact") -> dict[str, Any]:
    return {
        "provider": "anilist",
        "media_id": media_id,
        "episode": episode,
        "airing_at": timestamp,
        "precision": precision,
        "inference_source": "test" if precision == "estimated" else "",
    }


def mapped_media(media_id: str = "123") -> dict[str, Any]:
    return {
        "title": "Example Anime",
        "original_title": "Example Anime",
        "year": "2026",
        "status": "Releasing",
        "episodes": "12",
        "season_number": 1,
        "runtime": "24 min",
        "genres": ["Action"],
        "aliases": ["Example Anime"],
        "provider_title": {"english": "Example Anime", "romaji": "Example Anime", "native": ""},
        "studio": "Example Studio",
        "source": "AniList",
        "rating": "80%",
        "synopsis": "Example",
        "poster": "",
        "air_date": "2026-01-01",
        "next_airing_at": "2026-07-29T12:00:00Z",
        "airing_episode": "8",
        "airing_source": "AniList",
        "media_format": "Tv",
        "release_season": "Summer",
        "season_year": "2026",
        "start_date": "2026-01-01",
        "end_date": "",
        "source_material": "Manga",
        "country_of_origin": "JP",
        "is_adult": False,
        "anilist_updated_at": "2026-07-22T00:00:00Z",
        "provider_ids": {"anilist": media_id},
    }


def test_exact_airing_overwrites_estimate_and_estimate_cannot_replace_exact(tmp_path) -> None:
    repository = SQLiteAiringRepository(tmp_path / "state.sqlite3")
    repository.upsert([airing("123", 1, "2026-01-01T12:00:00Z", "estimated")])
    repository.upsert([airing("123", 1, "2026-01-02T12:00:00Z", "exact")])
    repository.upsert([airing("123", 1, "2026-01-03T12:00:00Z", "estimated")])

    records = repository.for_media("123")

    assert records[0]["airing_at"] == "2026-01-02T12:00:00Z"
    assert records[0]["precision"] == "exact"


def test_anilist_snapshot_combines_metadata_past_and_future_in_one_callback(monkeypatch) -> None:
    calls = []

    def fake_post(_url: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {
            "data": {
                "Media": {
                    "id": 123,
                    "title": {"english": "Example Anime", "romaji": "Example Anime", "native": ""},
                    "synonyms": [],
                    "seasonYear": 2026,
                    "status": "RELEASING",
                    "episodes": 12,
                    "duration": 24,
                    "averageScore": 80,
                    "genres": ["Action"],
                    "coverImage": {"large": ""},
                    "studios": {"nodes": [{"name": "Example Studio"}]},
                },
                "past": {"airingSchedules": [{"mediaId": 123, "episode": 7, "airingAt": 1784131200}]},
                "future": {"airingSchedules": [{"mediaId": 123, "episode": 8, "airingAt": 1784736000}]},
            }
        }

    monkeypatch.setattr(metadata, "_post_json", fake_post)

    snapshot = metadata.fetch_anilist_snapshot("123")

    assert len(calls) == 1
    assert snapshot is not None
    assert snapshot["media"]["provider_ids"]["anilist"] == 123
    assert snapshot["past_airings"][0]["episode"] == 7
    assert snapshot["future_airings"][0]["episode"] == 8


def test_unified_refresh_updates_metadata_and_exact_airing_state_with_one_fetch(monkeypatch, tmp_path) -> None:
    repository = SQLiteAiringRepository(tmp_path / "state.sqlite3")
    anime = {
        "library_id": "example",
        "title": "Example Anime",
        "original_title": "Example Anime",
        "provider_ids": {"anilist": "123"},
        "torrent_search": {"candidates": [], "notices": []},
        "monitored": True,
    }
    database = {"anime": [anime], "settings": {}}
    calls = []
    now = datetime.now(timezone.utc).timestamp()

    def fake_snapshot(media_id: str) -> dict[str, Any]:
        calls.append(media_id)
        return {
            "media": mapped_media(media_id),
            "past_airings": [airing(media_id, 7, "2026-07-15T12:00:00Z")],
            "future_airings": [airing(media_id, 8, "2099-07-29T12:00:00Z")],
        }

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda _database: None)
    monkeypatch.setattr(app_state, "_airing_repository", lambda: repository)
    monkeypatch.setattr(app_state, "fetch_anilist_snapshot", fake_snapshot)
    monkeypatch.setattr(app_state, "_sync_anime_nfo_file", lambda _anime: False)

    summary = app_state.refresh_library_anilist_state(force=True)

    assert calls == ["123"]
    assert summary["updated"] == 1
    assert anime["aired_episode"] == "7"
    assert anime["airing_episode"] == "8"
    assert anime["source_material"] == "Manga"
    assert repository.for_media("123")[0]["precision"] == "exact"


class FakeCalendarRepository:
    def __init__(self) -> None:
        self.upserted: list[dict[str, Any]] = []
        self.coverage: list[tuple[list[str], str]] = []

    def for_range(self, *_args: Any, **_kwargs: Any) -> list[dict[str, Any]]:
        return []

    def missing_coverage(self, media_ids: list[str], _month: str) -> list[str]:
        return list(media_ids)

    def upsert(self, records: list[dict[str, Any]]) -> int:
        self.upserted.extend(records)
        return len(records)

    def mark_coverage(self, media_ids: list[str], month: str) -> None:
        self.coverage.append((list(media_ids), month))


def test_historical_calendar_enqueues_lazy_month_windows_without_provider_io(monkeypatch) -> None:
    repository = FakeCalendarRepository()
    jobs = []
    database = {
        "anime": [{"title": "Example Anime", "provider_ids": {"anilist": "123"}}],
        "settings": {"timezone": "GMT+8"},
    }
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_airing_repository", lambda: repository)
    monkeypatch.setattr(maintenance, "enqueue_job", lambda job_type, payload, **kwargs: jobs.append((job_type, payload, kwargs)) or "job")
    monkeypatch.setattr(
        app_state,
        "fetch_anilist_airing_window",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("calendar page must not block on AniList")),
    )

    model = app_state.calendar_model("month", "2020-02-15")

    assert model["history_pending"] is True
    assert jobs
    assert {job[0] for job in jobs} == {"calendar_airing_window"}
    assert all(job[1]["media_ids"] == ["123"] for job in jobs)


def test_calendar_window_hydration_persists_exact_records_and_coverage(monkeypatch) -> None:
    repository = FakeCalendarRepository()
    record = airing("123", 4, "2020-02-20T12:00:00Z")
    monkeypatch.setattr(app_state, "_airing_repository", lambda: repository)
    monkeypatch.setattr(app_state, "fetch_anilist_airing_window", lambda *_args, **_kwargs: ([record], False))

    app_state.hydrate_calendar_airing_window({"media_ids": ["123"], "utc_month": "2020-02", "page": 1})

    assert repository.upserted == [record]
    assert repository.coverage == [(["123"], "2020-02")]
