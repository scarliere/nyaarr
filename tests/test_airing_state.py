from __future__ import annotations

from nyaarr import app_state


def test_upcoming_status_with_later_airing_episode_is_airing() -> None:
    anime = {
        "status": "Upcoming",
        "airing_episode": "12",
        "next_airing_at": "2026-08-12T13:00:00Z",
    }

    assert app_state._airing_state(anime) == "Airing"


def test_upcoming_status_without_aired_episode_remains_not_yet_aired() -> None:
    anime = {
        "status": "Upcoming",
        "airing_episode": "1",
        "next_airing_at": "2026-08-12T13:00:00Z",
    }

    assert app_state._airing_state(anime) == "Not Yet Aired"


def test_airing_schedule_refresh_prefers_existing_anilist_id(monkeypatch) -> None:
    calls = []
    anime = {
        "title": "Re:ZERO -Starting Life in Another World- Season 4",
        "status": "Upcoming",
        "airing_episode": "12",
        "provider_ids": {"anilist": "189046", "kitsu": "49746"},
        "episodes": "19",
        "monitored": True,
    }

    def fake_search_by_id(anilist_id):
        calls.append(anilist_id)
        return {
            "title": "Re:ZERO -Starting Life in Another World- Season 4",
            "status": "Releasing",
            "source": "AniList",
            "air_date": "2026-07-01",
            "next_airing_at": "2026-07-01T13:00:00Z",
            "airing_episode": "13",
            "airing_source": "AniList",
            "provider_ids": {"anilist": "189046"},
        }

    monkeypatch.setattr(app_state, "search_anilist_by_id", fake_search_by_id)
    monkeypatch.setattr(app_state, "search_anime_metadata", lambda query: (_ for _ in ()).throw(AssertionError("title search should not run")))

    assert app_state._refresh_anime_airing_schedule(anime, 1780000000) is True
    assert calls == ["189046"]
    assert anime["status"] == "Releasing"
    assert anime["airing_state"] == "Airing"
    assert anime["airing_schedule_source"] == "AniList"


def test_airing_schedule_refresh_clears_stale_next_airing_after_finale(monkeypatch) -> None:
    anime = {
        "title": "Petals of Reincarnation",
        "status": "Releasing",
        "next_airing_at": "2026-06-26T12:00:00Z",
        "airing_episode": "13",
        "airing_source": "AniList",
        "provider_ids": {"anilist": "179950"},
        "episodes": "13",
        "episode_files": [f"/anime/Petals.S01E{episode:02d}.mkv" for episode in range(1, 14)],
        "monitored": True,
    }

    def fake_search_by_id(anilist_id):
        assert anilist_id == "179950"
        return {
            "title": "Petals of Reincarnation",
            "status": "Finished",
            "source": "AniList",
            "air_date": "2026-06-26",
            "next_airing_at": "",
            "airing_episode": "",
            "airing_source": "",
            "provider_ids": {"anilist": "179950"},
        }

    monkeypatch.setattr(app_state, "search_anilist_by_id", fake_search_by_id)

    assert app_state._refresh_anime_airing_schedule(anime, 1780000000) is True
    assert anime["status"] == "Finished"
    assert anime["next_airing_at"] == ""
    assert anime["airing_episode"] == ""
    assert anime["airing_source"] == ""
    assert anime["airing_state"] == "Completed"
    assert anime["library_state"] == "Completed"


def test_airing_schedule_refresh_is_due_after_one_minute(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "AIRING_REFRESH_MAX_AGE_SECONDS", 60)
    anime = {
        "status": "Releasing",
        "airing_episode": "13",
        "airing_schedule_checked_at": "1970-01-01T00:00:00Z",
    }

    assert app_state._should_refresh_airing_schedule(anime, 59, False) is False
    assert app_state._should_refresh_airing_schedule(anime, 61, False) is True


def test_calendar_item_displays_airing_time_in_gmt_plus_8() -> None:
    settings = {"timezone": "GMT+8"}
    item = app_state._calendar_item(
        {
            "title": "DIGIMON BEATBREAK",
            "next_airing_at": "2026-07-04T16:30:00Z",
            "airing_episode": "29",
        },
        settings,
    )

    assert item["time"] == "00:30 GMT+8"


def test_calendar_air_date_uses_gmt_plus_8_day_boundary() -> None:
    settings = {"timezone": "GMT+8"}
    anime = {"next_airing_at": "2026-07-04T16:30:00Z"}

    assert app_state._anime_air_date(anime, settings).isoformat() == "2026-07-05"
    assert app_state._display_datetime_label("2026-07-04T16:30:00Z", settings) == "05 Jul 2026 00:30 GMT+8"


def test_calendar_uses_configured_timezone() -> None:
    settings = {"timezone": "UTC"}
    anime = {"next_airing_at": "2026-07-04T16:30:00Z"}
    item = app_state._calendar_item(
        {
            "title": "DIGIMON BEATBREAK",
            "next_airing_at": "2026-07-04T16:30:00Z",
            "airing_episode": "29",
        },
        settings,
    )

    assert item["time"] == "16:30 UTC"
    assert app_state._anime_air_date(anime, settings).isoformat() == "2026-07-04"
    assert app_state._display_datetime_label("2026-07-04T16:30:00Z", settings) == "04 Jul 2026 16:30 UTC"


