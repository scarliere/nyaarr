from __future__ import annotations

import nyaarr


def _fake_result() -> dict[str, object]:
    return {
        "title": "Async Anime",
        "original_title": "Async Anime JP",
        "year": "2026",
        "status": "Releasing",
        "episodes": "12",
        "season_number": 1,
        "runtime": "24 min",
        "genres": ["Action"],
        "studio": "Studio",
        "source": "AniList",
        "rating": "80%",
        "synopsis": "A test result.",
        "poster": "",
        "air_date": "2026-06-26",
        "next_airing_at": "",
        "airing_episode": "2",
        "airing_source": "AniList",
        "provider_ids": {"anilist": "123"},
    }


def test_add_page_with_query_renders_before_metadata_search(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: {"anime": 0, "manual_selection": 0, "activity": 0, "wanted": 0, "settings_missing": 0})
    monkeypatch.setattr(nyaarr, "search_anime_metadata", lambda query: calls.append(query) or ([], []))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/add?q=rezero")

    assert response.status_code == 200
    assert calls == []
    assert b"Searching metadata" in response.data
    assert b"data-search-url=\"/add/search\"" in response.data


def test_add_search_endpoint_runs_metadata_search_and_returns_partial(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: {"anime": 0, "manual_selection": 0, "activity": 0, "wanted": 0, "settings_missing": 0})
    monkeypatch.setattr(nyaarr, "search_anime_metadata", lambda query: calls.append(query) or ([_fake_result()], []))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/add/search?q=rezero", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert calls == ["rezero"]
    payload = response.get_json()
    assert payload["total_results"] == 1
    assert "Async Anime" in payload["html"]
    assert "add-anime-action" in payload["html"]


def test_activity_pages_render_before_activity_model(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: _sidebar_counts())
    monkeypatch.setattr(nyaarr, "activity_model", lambda section="queued": calls.append(section) or nyaarr._empty_activity_model(section))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    for route, data_url in (
        ("/activity", "/activity/queued/data"),
        ("/activity/history", "/activity/history/data"),
        ("/activity/blocked", "/activity/blocked/data"),
    ):
        response = client.get(route)
        assert response.status_code == 200, route
        assert data_url.encode() in response.data
        assert b"Loading activity." in response.data
        assert b"table-loading-card" in response.data

    assert calls == []


def test_activity_data_endpoint_returns_activity_model(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: {"anime": 0, "manual_selection": 0, "activity": 1, "wanted": 0, "settings_missing": 0})
    monkeypatch.setattr(
        nyaarr,
        "activity_model",
        lambda section: {
            "section": section,
            "label": "Queued",
            "description": "Queued downloads.",
            "rows": [{"anime": "Petals", "episode": "1", "progress": 2}],
            "counts": {"queued": 1, "history": 0, "blocked": 0},
        },
    )
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/activity/queued/data", headers={"Accept": "application/json"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["section"] == "queued"
    assert payload["rows"][0]["progress"] == 2
    assert payload["counts"]["queued"] == 1


def _sidebar_counts() -> dict[str, int]:
    return {
        "anime": 0,
        "manual_selection": 0,
        "metadata_verification": 0,
        "activity": 0,
        "wanted": 0,
        "settings_missing": 0,
        "events": 0,
    }


def test_metadata_review_and_logs_pages_render(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "metadata_verification_model", lambda: {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "event_log_model", lambda: {"rows": [], "count": 0})
    monkeypatch.setattr(nyaarr, "event_log_rows", lambda limit=100: [])
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    metadata_response = client.get("/anime/metadata-verification")
    logs_response = client.get("/system/logs")
    events_response = client.get("/system/events")
    csv_response = client.get("/system/logs.csv")

    assert metadata_response.status_code == 200
    assert b"Metadata Review" in metadata_response.data
    assert logs_response.status_code == 200
    assert b"Logs" in logs_response.data
    assert events_response.status_code == 200
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"


def test_primary_pages_render_stable_initial_models(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: calls.append("sidebar") or _sidebar_counts())
    monkeypatch.setattr(nyaarr, "anime_library", lambda: calls.append("anime_library") or [])
    monkeypatch.setattr(nyaarr, "library_stats", lambda: calls.append("library_stats") or [])
    monkeypatch.setattr(nyaarr, "manual_selection_model", lambda: calls.append("manual_selection") or {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "metadata_verification_model", lambda: calls.append("metadata") or {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "calendar_model", lambda view="week", anchor_date=None: calls.append("calendar") or nyaarr._empty_calendar_model(view, anchor_date))
    monkeypatch.setattr(nyaarr, "activity_model", lambda section="queued": calls.append(f"activity:{section}") or nyaarr._empty_activity_model(section))
    monkeypatch.setattr(nyaarr, "user_settings", lambda: calls.append("settings") or nyaarr._empty_settings_model())
    monkeypatch.setattr(nyaarr, "root_folder_missing", lambda: calls.append("root_missing") or True)
    monkeypatch.setattr(nyaarr, "event_log_model", lambda: calls.append("events") or {"rows": [], "count": 0})
    monkeypatch.setattr(nyaarr, "system_status_model", lambda: calls.append("status") or nyaarr._empty_system_status_model())

    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    routes = (
        "/",
        "/anime/list",
        "/anime/manual-selection",
        "/anime/metadata-verification",
        "/calendar",
        "/activity",
        "/activity/history",
        "/activity/blocked",
        "/settings",
        "/system/logs",
        "/system/events",
        "/system/status",
    )
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route
        if route in {"/anime/manual-selection", "/anime/metadata-verification", "/system/logs", "/system/events"}:
            assert b"<main class=\"app-shell\" data-async-page-url" in response.data, route
        else:
            assert b"<main class=\"app-shell\" data-async-page-url" not in response.data, route

    assert "anime_library" in calls
    assert "library_stats" in calls
    assert "manual_selection" not in calls
    assert "metadata" not in calls
    assert "calendar" in calls
    assert "activity:queued" not in calls
    assert "activity:history" not in calls
    assert "activity:blocked" not in calls
    assert "settings" in calls
    assert "root_missing" in calls
    assert "events" not in calls
    assert "status" in calls
    assert "sidebar" in calls


def test_async_table_pages_render_loading_table_placeholders(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "manual_selection_model", lambda: {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "metadata_verification_model", lambda: {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "event_log_model", lambda: {"rows": [], "count": 0})
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    for route in ("/anime/manual-selection", "/anime/metadata-verification", "/system/logs"):
        response = client.get(route)
        assert response.status_code == 200, route
        assert b"table-loading-card" in response.data, route


def test_async_data_endpoints_load_models_after_page_render(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "anime_library", lambda: calls.append("anime_library") or [])
    monkeypatch.setattr(nyaarr, "library_stats", lambda: calls.append("library_stats") or [])
    monkeypatch.setattr(nyaarr, "manual_selection_model", lambda: calls.append("manual_selection") or {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "metadata_verification_model", lambda: calls.append("metadata") or {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "calendar_model", lambda view="week", anchor_date=None: calls.append("calendar") or nyaarr._empty_calendar_model(view, anchor_date))
    monkeypatch.setattr(nyaarr, "activity_model", lambda section="queued": calls.append(f"activity:{section}") or nyaarr._empty_activity_model(section))
    monkeypatch.setattr(nyaarr, "user_settings", lambda: calls.append("settings") or nyaarr._empty_settings_model())
    monkeypatch.setattr(nyaarr, "root_folder_missing", lambda: calls.append("root_missing") or True)
    monkeypatch.setattr(nyaarr, "event_log_model", lambda: calls.append("events") or {"rows": [], "count": 0})
    monkeypatch.setattr(nyaarr, "system_status_model", lambda: calls.append("status") or nyaarr._empty_system_status_model())
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = app.test_client()

    routes = (
        "/anime/list/data-page",
        "/anime/manual-selection/data-page",
        "/anime/metadata-verification/data-page",
        "/calendar/data-page",
        "/activity/queued/page-data",
        "/activity/history/page-data",
        "/activity/blocked/page-data",
        "/settings/data-page",
        "/system/logs/data-page",
        "/system/events/data-page",
        "/system/status/data-page",
    )
    for route in routes:
        assert client.get(route).status_code == 200, route

    assert "anime_library" in calls
    assert "manual_selection" in calls
    assert "metadata" in calls
    assert "calendar" in calls
    assert "activity:queued" not in calls
    assert "activity:history" not in calls
    assert "activity:blocked" not in calls
    assert "settings" in calls
    assert "root_missing" in calls
    assert "events" in calls
    assert "status" in calls


def test_anime_detail_anilist_override_route_redirects(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "apply_manual_anilist_id", lambda library_id, anilist_id: calls.append((library_id, anilist_id)) or (True, "Updated from AniList."))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().post("/anime/anime-1/anilist-id", data={"anilist_id": "7465"})

    assert response.status_code == 302
    assert calls == [("anime-1", "7465")]
    assert "anilist_saved=1" in response.headers["Location"]

def test_anime_detail_page_renders_model(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(
        nyaarr,
        "anime_detail_model",
        lambda library_id: {
            "library_id": library_id,
            "title": "Petals of Reincarnation",
            "original_title": "Reincarnation no Kaben",
            "poster": "",
            "synopsis": "A simple anime detail page.",
            "year": "2026",
            "status": "Releasing",
            "library_state": "Monitored",
            "airing_state": "Airing",
            "air_date": "01 Apr 2026",
            "runtime": "24 min",
            "studio": "Studio",
            "source": "AniList",
            "rating": "80%",
            "genres": ["Action"],
            "quality_profile": "Up to: 1080p",
            "quality_resolution": "1080p",
            "anilist_id": "123",
            "manual_anilist_id": "",
            "completion": {"local_episodes": 1, "progress_target": 2, "expected_episodes": 2},
            "local_path": "",
            "torrent_strategy": "",
            "episodes": [
                {"label": "S01E01", "title": "Episode 1", "air_date": "TBA", "status": "Downloaded", "tone": "downloaded", "quality": "1080p", "file": "Episode1.mkv", "path": "C:/Anime/Episode1.mkv", "progress": None},
                {"label": "S01E02", "title": "Episode 2", "air_date": "TBA", "status": "Missing", "tone": "missing", "quality": "1080p", "file": "", "path": "", "progress": None},
            ],
        },
    )
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = app.test_client().get("/anime/anime-1")

    assert response.status_code == 200
    assert b"Petals of Reincarnation" in response.data
    assert b"S01E01" in response.data
    assert b"Downloaded" in response.data
    assert b"Edit AniList ID" in response.data
    assert b"anilist-edit-dialog" in response.data
    assert b"Update AniList" not in response.data

