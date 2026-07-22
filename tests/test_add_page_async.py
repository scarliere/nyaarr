from __future__ import annotations

from pathlib import Path

import pytest

import nyaarr



@pytest.fixture(autouse=True)
def _authenticated_app(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "has_superadmin_account", lambda: True)
    monkeypatch.setattr(nyaarr, "load_or_create_session_secret", lambda: "test-secret")
    monkeypatch.setattr(nyaarr, "_session_is_authenticated", lambda: True)


def _authenticated_client(app):
    client = app.test_client()
    with client.session_transaction() as session:
        session["superadmin_authenticated"] = True
        session["superadmin_username"] = "admin"
    return client

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

    response = _authenticated_client(app).get("/add?q=rezero")

    assert response.status_code == 200
    assert calls == []
    assert b"Searching metadata" in response.data
    assert b"data-search-url=\"/add/search\"" in response.data


def test_ui_bootstrap_combines_counts_jobs_and_revision(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, 'start_periodic_maintenance', lambda: None)
    monkeypatch.setattr(
        nyaarr,
        'ui_bootstrap_model',
        lambda: {
            'revision': 7,
            'sidebar_counts': _sidebar_counts() | {'activity': 2},
            'missing_settings': {'count': 0, 'missing': []},
            'root_scan': {'active': False},
            'jobs': {'active': 1, 'counts': {'running': 1}},
        },
    )
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get('/api/ui/bootstrap', headers={'Accept': 'application/json'})

    assert response.status_code == 200
    assert response.get_json()['sidebar_counts']['activity'] == 2
    assert response.headers['ETag'] == '"7"'

    unchanged = _authenticated_client(app).get(
        '/api/ui/bootstrap',
        headers={'Accept': 'application/json', 'If-None-Match': response.headers['ETag']},
    )
    assert unchanged.status_code == 304


def test_add_search_endpoint_runs_metadata_search_and_returns_partial(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: {"anime": 0, "manual_selection": 0, "activity": 0, "wanted": 0, "settings_missing": 0})
    monkeypatch.setattr(nyaarr, "search_anime_metadata", lambda query: calls.append(query) or ([_fake_result()], []))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get("/add/search?q=rezero", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert calls == ["rezero"]
    payload = response.get_json()
    assert payload["total_results"] == 1
    assert "Async Anime" in payload["html"]
    assert "add-anime-action" in payload["html"]
    assert 'name="provider_ids"' in payload["html"]
    assert "anilist" in payload["html"]


def test_add_anime_json_redirects_to_anime_list(monkeypatch) -> None:
    added = []
    result = _fake_result()
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: _sidebar_counts())
    monkeypatch.setattr(nyaarr, "add_anime_to_library", lambda anime, torrent_search, supplied_link="": added.append((anime, torrent_search, supplied_link)))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).post(
        "/anime",
        data={
            "library_id": "AniList:123",
            "title": result["title"],
            "original_title": result["original_title"],
            "year": result["year"],
            "status": result["status"],
            "episodes": result["episodes"],
            "season_number": str(result["season_number"]),
            "runtime": result["runtime"],
            "genres": "Action",
            "studio": result["studio"],
            "source": result["source"],
            "rating": result["rating"],
            "synopsis": result["synopsis"],
            "poster": result["poster"],
            "air_date": result["air_date"],
            "next_airing_at": result["next_airing_at"],
            "airing_episode": result["airing_episode"],
            "airing_source": result["airing_source"],
            "provider_ids": '{"anilist":"123"}',
            "aliases": '["Async Anime", "Async Romaji"]',
            "provider_title": '{"english":"Async Anime","romaji":"Async Romaji"}',
            "quality_resolution": "1080p",
            "nyaa_link": "",
        },
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["redirect_url"] == "/anime/list"
    assert added and added[0][0]["title"] == "Async Anime"
    assert added[0][0]["provider_ids"] == {"anilist": "123"}
    assert added[0][0]["aliases"] == ["Async Anime", "Async Romaji"]
    assert added[0][0]["provider_title"] == {"english": "Async Anime", "romaji": "Async Romaji"}

def test_activity_pages_render_before_activity_model(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: _sidebar_counts())
    monkeypatch.setattr(nyaarr, "activity_model", lambda section="queued": calls.append(section) or nyaarr._empty_activity_model(section))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = _authenticated_client(app)

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

    response = _authenticated_client(app).get("/activity/queued/data", headers={"Accept": "application/json"})

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
    client = _authenticated_client(app)

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
    monkeypatch.setattr(nyaarr, "dashboard_page_model", lambda: calls.append("dashboard") or {"anime_cards": [], "stats": [], "dashboard": nyaarr._empty_dashboard_model()})
    monkeypatch.setattr(nyaarr, "anime_list_page_model", lambda: calls.append("anime_list") or {"anime_cards": [], "revision": 1})

    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = _authenticated_client(app)

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
        if route in {
            "/", "/anime/list", "/anime/manual-selection", "/anime/metadata-verification",
            "/calendar", "/settings", "/system/logs", "/system/events", "/system/status",
        }:
            assert b"<main class=\"app-shell\" data-async-page-url" in response.data, route
        else:
            assert b"<main class=\"app-shell\" data-async-page-url" not in response.data, route

    assert "anime_library" not in calls
    assert "library_stats" not in calls
    assert "manual_selection" not in calls
    assert "metadata" not in calls
    assert "calendar" not in calls
    assert "activity:queued" not in calls
    assert "activity:history" not in calls
    assert "activity:blocked" not in calls
    assert "settings" not in calls
    assert "root_missing" not in calls
    assert "events" not in calls
    assert "status" not in calls
    assert "sidebar" not in calls


def test_base_shell_polls_root_scan_progress_for_sidebar_badges(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "anime_library", lambda: [])
    monkeypatch.setattr(nyaarr, "library_stats", lambda: {})
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get("/anime/list")

    assert response.status_code == 200
    assert b'/settings/root-folder/progress' in response.data
    assert b'startRootScanSidebarWatcher' in response.data
    assert b'window.refreshSidebarCounts = refreshSidebarCounts' in response.data
    assert b'scheduleRootScanSidebarWatcher(10000)' in response.data



def test_settings_preferred_subbers_tooltip_explains_separators(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(
        nyaarr,
        "user_settings",
        lambda: nyaarr._empty_settings_model()
        | {"preferred_subbers_text": "SubsPlease", "torrent_confidence_threshold": 70},
    )
    monkeypatch.setattr(nyaarr, "root_folder_missing", lambda: True)
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get("/settings")

    assert response.status_code == 200
    assert b"Preferred subbers format" in response.data
    assert b"separate names with commas" in response.data
    assert b"Order matters" in response.data
    assert b"Spaces alone are not separators" in response.data

def test_settings_root_scan_starts_global_sidebar_watcher(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "user_settings", lambda: nyaarr._empty_settings_model())
    monkeypatch.setattr(nyaarr, "root_folder_missing", lambda: True)
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get("/settings")

    assert response.status_code == 200
    assert b'window.startRootScanSidebarWatcher(1000)' in response.data
    assert b'window.refreshSidebarCounts' in response.data


def test_shared_list_pages_use_session_cache_before_refetching() -> None:
    root = Path(__file__).resolve().parents[1]
    base = (root / 'nyaarr' / 'templates' / 'base.html').read_text(encoding='utf-8')
    activity = (root / 'nyaarr' / 'templates' / 'activity.html').read_text(encoding='utf-8')
    add_page = (root / 'nyaarr' / 'templates' / 'add_anime.html').read_text(encoding='utf-8')
    detail = (root / 'nyaarr' / 'templates' / 'anime_detail.html').read_text(encoding='utf-8')

    assert 'nyaarr:list-cache:v1:' in base
    assert 'window.sessionStorage' in base
    assert 'if (cachedPage.fresh) return;' in base
    assert 'nyaarrListCache.clear();' in base
    assert 'const cacheKey = `nyaarr:list-cache:v1:${bootstrapUrl}`;' in base
    assert 'nyaarrListCache.set("{{ url_for(\'ui_bootstrap_data\') }}", uiBootstrapResult);' in base
    assert 'cachedActivity.fresh' in activity
    assert 'cachedSearch.fresh' in add_page
    assert 'cachedTitles.fresh' in detail


def test_async_table_pages_render_loading_table_placeholders(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "manual_selection_model", lambda: {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "metadata_verification_model", lambda: {"items": [], "count": 0})
    monkeypatch.setattr(nyaarr, "event_log_model", lambda: {"rows": [], "count": 0})
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = _authenticated_client(app)

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
    monkeypatch.setattr(nyaarr, "dashboard_page_model", lambda: calls.append("dashboard") or {"anime_cards": [], "stats": [], "dashboard": nyaarr._empty_dashboard_model()})
    monkeypatch.setattr(nyaarr, "anime_list_page_model", lambda: calls.append("anime_list") or {"anime_cards": [], "revision": 1})
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = _authenticated_client(app)

    routes = (
        "/dashboard/data-page",
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

    assert "dashboard" in calls
    assert "anime_list" in calls
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


def test_dashboard_and_anime_list_have_distinct_content(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(
        nyaarr,
        "dashboard_page_model",
        lambda: {"anime_cards": [], "stats": [], "dashboard": nyaarr._empty_dashboard_model()},
    )
    monkeypatch.setattr(nyaarr, "anime_list_page_model", lambda: {"anime_cards": [], "revision": 1})
    app = nyaarr.create_app()
    app.config.update(TESTING=True)
    client = _authenticated_client(app)

    dashboard = client.get("/dashboard/data-page")
    anime_list = client.get("/anime/list/data-page")
    shell = client.get("/")

    assert b"What needs attention" in dashboard.data
    assert b"Active downloads" in dashboard.data
    assert b"Anime library" in dashboard.data
    assert b"What needs attention" not in anime_list.data
    assert b"Active downloads" not in anime_list.data
    assert b"Anime library" in anime_list.data
    assert b"Health" in anime_list.data
    assert b">Dashboard</span>" in shell.data
    assert b'href="/anime/list"' in shell.data


def test_anime_detail_anilist_override_route_redirects(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(nyaarr, "apply_manual_anilist_id", lambda library_id, anilist_id: calls.append((library_id, anilist_id)) or (True, "Updated from AniList."))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).post("/anime/anime-1/anilist-id", data={"anilist_id": "7465"})

    assert response.status_code == 302
    assert calls == [("anime-1", "7465")]
    assert "anilist_saved=1" in response.headers["Location"]


def test_anime_detail_episode_manual_link_route_redirects(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(
        nyaarr,
        "assign_manual_torrent_url",
        lambda library_id, torrent_link, episode: calls.append((library_id, torrent_link, episode)) or (True, "Manual torrent link was sent to qBittorrent."),
    )
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).post(
        "/anime/anime-1/episodes/manual-link",
        data={"episode": "120", "torrent_link": "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12"},
    )

    assert response.status_code == 302
    assert calls == [("anime-1", "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12", "120")]
    assert "detail_saved=1" in response.headers["Location"]

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
                {"label": "S01E01", "episode": 1, "title": "Episode 1", "air_date": "TBA", "status": "Downloaded", "tone": "downloaded", "quality": "1080p", "file": "Episode1.mkv", "path": "C:/Anime/Episode1.mkv", "progress": None},
                {"label": "S01E02", "episode": 2, "title": "Episode 2", "air_date": "TBA", "status": "Missing", "tone": "missing", "quality": "1080p", "file": "", "path": "", "progress": None},
            ],
        },
    )
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get("/anime/anime-1")

    assert response.status_code == 200
    assert b"Petals of Reincarnation" in response.data
    assert b"S01E01" in response.data
    assert b"Downloaded" in response.data
    assert b"Options" in response.data
    assert b"Correct metadata match" in response.data
    assert b"anime-manage-dialog" in response.data
    assert b"Update AniList" not in response.data
    assert b"/anime/anime-1/episodes/manual-link" in response.data
    assert b'name="episode" value="2"' in response.data
    assert b"Magnet link or .torrent URL" in response.data
    assert b"<th>Action</th>" not in response.data


def test_anime_episode_titles_endpoint_returns_cached_best_effort_titles(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", _sidebar_counts)
    monkeypatch.setattr(
        nyaarr,
        "anime_episode_titles_model",
        lambda library_id: {
            "titles": {"1": "The Journey's End"},
            "pending": library_id == "anime-1",
            "source": "Jikan",
        },
    )
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).get(
        "/anime/anime-1/episode-titles",
        headers={"Accept": "application/json"},
    )

    assert response.status_code == 200
    assert response.get_json() == {
        "ok": True,
        "titles": {"1": "The Journey's End"},
        "pending": True,
        "source": "Jikan",
    }


def test_download_client_save_json_returns_redirect(monkeypatch) -> None:
    saved = []
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    monkeypatch.setattr(nyaarr, "sidebar_counts", lambda: _sidebar_counts())
    monkeypatch.setattr(nyaarr, "save_download_client", lambda form: saved.append(dict(form)) or (True, "Download client saved."))
    app = nyaarr.create_app()
    app.config.update(TESTING=True)

    response = _authenticated_client(app).post(
        "/settings/download-client",
        data={
            "implementation": "qbittorrent",
            "name": "qBittorrent",
            "host": "localhost",
            "port": "8080",
            "category": "nyaarr",
            "enabled": "on",
        },
        headers={"Accept": "application/json", "X-Requested-With": "fetch"},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload == {"ok": True, "message": "Download client saved.", "redirect_url": "/settings?client_saved=1&client_message=Download+client+saved."}
    assert saved and saved[0]["implementation"] == "qbittorrent"
