from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from nyaarr import app_state, maintenance
from nyaarr.episode_title_repository import SQLiteEpisodeTitleRepository
from nyaarr.jikan_client import JikanClient


def title_record(mal_id: str, episode: int, title: str) -> dict[str, Any]:
    return {
        "provider": "jikan",
        "mal_id": mal_id,
        "episode": episode,
        "title": title,
        "title_japanese": "",
        "title_romanji": "",
        "aired_at": "",
        "filler": False,
        "recap": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }


def test_jikan_client_maps_paginated_episode_titles(monkeypatch) -> None:
    client = JikanClient(request_interval_seconds=1, cache_ttl_seconds=0)
    monkeypatch.setattr(
        client,
        "_get_json",
        lambda _path: {
            "pagination": {"last_visible_page": 2, "has_next_page": True},
            "data": [
                {
                    "mal_id": 1,
                    "title": "The Journey's End",
                    "title_japanese": "冒険の終わり",
                    "title_romanji": "Bouken no Owari",
                    "aired": "2023-09-29T00:00:00+00:00",
                    "filler": False,
                    "recap": False,
                }
            ],
        },
    )

    result = client.fetch_episode_page("52991", page=1)

    assert result["mal_id"] == "52991"
    assert result["has_next_page"] is True
    assert result["last_visible_page"] == 2
    assert result["records"][0]["title"] == "The Journey's End"
    assert result["records"][0]["episode"] == 1


def test_episode_title_repository_persists_titles_and_preserves_nonempty_values(tmp_path) -> None:
    database_path = tmp_path / "state.sqlite3"
    repository = SQLiteEpisodeTitleRepository(database_path)
    repository.upsert([title_record("52991", 1, "The Journey's End")])
    repository.upsert([title_record("52991", 1, "")])

    reopened = SQLiteEpisodeTitleRepository(database_path)

    assert reopened.for_anime("52991")[0]["title"] == "The Journey's End"
    assert reopened.is_due("52991", max_age_seconds=3600) is True
    reopened.mark_requested("52991")
    assert reopened.is_pending("52991") is True
    assert reopened.is_due("52991", max_age_seconds=3600) is False
    reopened.mark_complete("52991", last_visible_page=1, record_count=1)
    assert reopened.is_pending("52991") is False
    assert reopened.is_due("52991", max_age_seconds=3600) is False


def test_anime_detail_uses_cached_title_and_only_queues_background_refresh(
    monkeypatch,
    tmp_path,
) -> None:
    repository = SQLiteEpisodeTitleRepository(tmp_path / "state.sqlite3")
    repository.upsert([title_record("52991", 1, "The Journey's End")])
    jobs = []
    anime = {
        "library_id": "frieren",
        "title": "Frieren",
        "original_title": "Sousou no Frieren",
        "status": "Finished",
        "episodes": "2",
        "provider_ids": {"anilist": "154587", "mal": "52991"},
        "completion": {"expected_episodes": 2, "progress_target": 2, "local_episodes": 0},
        "torrent_search": {"candidates": [], "notices": []},
        "monitored": True,
    }
    database = {"anime": [anime], "settings": {}}
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_episode_title_repository", lambda: repository)
    monkeypatch.setattr(app_state, "_airing_repository", lambda: type("Repo", (), {"for_media": lambda self, _id: []})())
    monkeypatch.setattr(
        maintenance,
        "enqueue_job",
        lambda job_type, payload, **kwargs: jobs.append((job_type, payload, kwargs)) or "job",
    )
    monkeypatch.setattr(
        app_state.jikan_client,
        "fetch_episode_page",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("page render must not call Jikan")),
    )

    model = app_state.anime_detail_model("frieren")

    assert model is not None
    assert model["episodes"][0]["title"] == "The Journey's End"
    assert model["episodes"][1]["title"] == "Episode 2"
    assert model["episode_titles_pending"] is True
    assert jobs[0][0] == "jikan_episode_titles"
    assert jobs[0][1] == {"mal_id": "52991", "page": 1}


def test_jikan_hydration_continues_pages_then_marks_cache_complete(monkeypatch, tmp_path) -> None:
    repository = SQLiteEpisodeTitleRepository(tmp_path / "state.sqlite3")
    repository.mark_requested("21")
    jobs = []
    responses = {
        1: {
            "mal_id": "21",
            "page": 1,
            "last_visible_page": 2,
            "has_next_page": True,
            "records": [title_record("21", 1, "I'm Luffy!")],
        },
        2: {
            "mal_id": "21",
            "page": 2,
            "last_visible_page": 2,
            "has_next_page": False,
            "records": [title_record("21", 101, "A Heated Battle!")],
        },
    }
    monkeypatch.setattr(app_state, "_episode_title_repository", lambda: repository)
    monkeypatch.setattr(
        app_state.jikan_client,
        "fetch_episode_page",
        lambda _mal_id, page=1: responses[page],
    )
    monkeypatch.setattr(
        maintenance,
        "enqueue_job",
        lambda job_type, payload, **kwargs: jobs.append((job_type, payload, kwargs)) or "job",
    )

    app_state.hydrate_jikan_episode_titles({"mal_id": "21", "page": 1})
    assert jobs[0][1] == {"mal_id": "21", "page": 2}
    assert repository.is_pending("21") is True

    app_state.hydrate_jikan_episode_titles({"mal_id": "21", "page": 2})

    assert [record["episode"] for record in repository.for_anime("21")] == [1, 101]
    assert repository.is_pending("21") is False
    assert repository.is_due("21", max_age_seconds=3600) is False


def test_episode_title_json_model_keeps_number_fallback_out_of_payload(monkeypatch, tmp_path) -> None:
    repository = SQLiteEpisodeTitleRepository(tmp_path / "state.sqlite3")
    repository.upsert([title_record("123", 1, "Named Episode"), title_record("123", 2, "")])
    repository.mark_complete("123", last_visible_page=1, record_count=2)
    database = {
        "anime": [
            {
                "library_id": "show",
                "status": "Finished",
                "provider_ids": {"mal": "123"},
            }
        ],
        "settings": {},
    }
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_episode_title_repository", lambda: repository)

    model = app_state.anime_episode_titles_model("show")

    assert model == {"titles": {"1": "Named Episode"}, "pending": False, "source": "Jikan"}
