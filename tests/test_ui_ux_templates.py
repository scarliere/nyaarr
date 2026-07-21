from __future__ import annotations

from pathlib import Path

import nyaarr


ROOT = Path(__file__).resolve().parents[1]


def _source(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_updated_ui_templates_compile(monkeypatch) -> None:
    monkeypatch.setattr(nyaarr, "start_periodic_maintenance", lambda: None)
    app = nyaarr.create_app()

    for name in (
        "base.html",
        "_metadata_results.html",
        "activity.html",
        "anime_detail.html",
        "calendar.html",
        "events.html",
        "manual_selection.html",
        "metadata_verification.html",
        "settings.html",
    ):
        app.jinja_env.get_template(name)


def test_anime_and_calendar_actions_are_progressively_disclosed() -> None:
    detail = _source("nyaarr/templates/anime_detail.html")
    calendar = _source("nyaarr/templates/calendar.html")

    assert "anime-manage-dialog" in detail
    assert "Assign source" in detail
    assert 'class="episode-file-name"' in detail
    assert "anime-preferences-panel" not in detail
    assert "calendar-jump-date" in calendar
    assert "url_for('anime_detail', library_id=item.library_id)" in calendar
    assert "calendar-overflow" in calendar


def test_dense_table_controls_keep_primary_actions_visible() -> None:
    activity = _source("nyaarr/templates/activity.html")
    manual = _source("nyaarr/templates/manual_selection.html")
    metadata = _source("nyaarr/templates/metadata_verification.html")
    logs = _source("nyaarr/templates/events.html")

    assert "<th>Episode</th>" in activity
    assert "Reject this torrent candidate?" in activity
    assert "<th>Type</th>" not in manual
    assert "<th>Link</th>" not in manual
    assert ">Select</button>" in manual
    assert "row-detail" in metadata
    assert "data-log-search" in logs
    assert "log-row-detail" in logs


def test_global_density_and_accessibility_css_is_present() -> None:
    css = _source("nyaarr/static/css/app.css")
    base = _source("nyaarr/templates/base.html")
    settings = _source("nyaarr/templates/settings.html")

    assert "@media (min-width: 761px)" in css
    assert "white-space: nowrap" in css
    assert "text-overflow: ellipsis" in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion: reduce" in css
    assert 'placeholder="Add Anime"' in base
    assert "Unable to load this page" in base
    assert "Test success" not in settings
    assert "Not tested" in settings
    assert "Transmission" not in settings
