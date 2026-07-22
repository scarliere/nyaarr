from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import subprocess
import time
import threading
import urllib.error
import urllib.request
from collections import Counter
from statistics import median
from xml.etree import ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from werkzeug.security import check_password_hash, generate_password_hash

from .airing_repository import SQLiteAiringRepository
from .episode_title_repository import SQLiteEpisodeTitleRepository
from .jikan_client import JikanNotFoundError, client as jikan_client
from .metadata import (
    MetadataProviderError,
    MetadataRateLimitError,
    fetch_anilist_airing_window,
    fetch_anilist_snapshot,
    search_anilist,
    search_anilist_by_id,
    search_anime_metadata,
    search_kitsu,
    search_tmdb,
)
from .qbittorrent_client import QBittorrentError, client_from_settings
from .persistence import REVISION_FIELD, SQLiteStateRepository
from .torrent_finder import _title_matches as torrent_title_matches
from .torrent_finder import _audio_preference_rank, _is_dub_release
from .torrent_finder import episode_number_from_title, find_torrents_for_anime, release_group_from_title


USER_DATA_DIR = Path("data/user")
USER_DATABASE_PATH = Path(os.environ.get("NYAARR_USER_DATABASE_PATH", USER_DATA_DIR / "anime-library.json"))
SESSION_SECRET_PATH = Path(os.environ.get("NYAARR_SESSION_SECRET_PATH", USER_DATA_DIR / "session-secret.key"))
RESOLVED_METADATA_CACHE_PATH = Path(
    os.environ.get("NYAARR_RESOLVED_METADATA_CACHE_PATH", "data/cache/resolved-anime-metadata.json")
)
COLD_STORAGE_DIR = Path(os.environ.get("NYAARR_COLD_STORAGE_DIR", USER_DATA_DIR / "cold"))
UNMONITORED_TITLES_COLD_STORAGE_PATH = Path(
    os.environ.get("NYAARR_UNMONITORED_TITLES_COLD_STORAGE_PATH", COLD_STORAGE_DIR / "unmonitored-titles.jsonl")
)
IGNORED_TORRENTS_COLD_STORAGE_PATH = Path(
    os.environ.get("NYAARR_IGNORED_TORRENTS_COLD_STORAGE_PATH", COLD_STORAGE_DIR / "ignored-torrents.jsonl")
)
DOWNLOAD_QUEUES_COLD_STORAGE_PATH = Path(
    os.environ.get("NYAARR_DOWNLOAD_QUEUES_COLD_STORAGE_PATH", COLD_STORAGE_DIR / "download-queues.jsonl")
)
METADATA_CANDIDATES_COLD_STORAGE_PATH = Path(
    os.environ.get("NYAARR_METADATA_CANDIDATES_COLD_STORAGE_PATH", COLD_STORAGE_DIR / "metadata-candidates.jsonl")
)
RESOLVED_METADATA_COLD_STORAGE_PATH = Path(
    os.environ.get("NYAARR_RESOLVED_METADATA_COLD_STORAGE_PATH", COLD_STORAGE_DIR / "resolved-metadata-cache.jsonl")
)
DATABASE_SCHEMA_VERSION = 1
DEFAULT_DISPLAY_TIMEZONE = "GMT+8"
DEFAULT_PREFERRED_SUBBERS = ["SubsPlease"]
DISPLAY_TIMEZONE_OPTIONS = [{"value": "UTC", "label": "UTC"}] + [
    {"value": f"GMT{offset:+d}", "label": f"GMT{offset:+d}"}
    for offset in range(-12, 15)
    if offset != 0
]
MEDIA_EXTENSIONS = {".avi", ".m2ts", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".ts", ".webm", ".wmv"}
DANGEROUS_TORRENT_EXTENSIONS = {
    ".001",
    ".7z",
    ".apk",
    ".app",
    ".bat",
    ".bin",
    ".bz2",
    ".cmd",
    ".com",
    ".cpl",
    ".deb",
    ".desktop",
    ".dll",
    ".dmg",
    ".exe",
    ".gz",
    ".hta",
    ".ipa",
    ".iso",
    ".jar",
    ".js",
    ".jse",
    ".lnk",
    ".msi",
    ".msp",
    ".php",
    ".pl",
    ".ps1",
    ".py",
    ".rar",
    ".reg",
    ".rpm",
    ".rb",
    ".scr",
    ".sh",
    ".sys",
    ".tar",
    ".torrent",
    ".url",
    ".vbe",
    ".vbs",
    ".wsf",
    ".xz",
    ".z",
    ".zip",
}
MEDIA_PROBE_BYTES = 16 * 1024 * 1024
FFPROBE_TIMEOUT_SECONDS = 20
AIRING_REFRESH_MAX_AGE_SECONDS = int(os.environ.get("NYAARR_AIRING_REFRESH_MAX_AGE_SECONDS", str(15 * 60)))
PERIODIC_MAINTENANCE_INTERVAL_SECONDS = int(os.environ.get("NYAARR_PERIODIC_MAINTENANCE_INTERVAL_SECONDS", "60"))
DOWNLOAD_QUEUE_REFRESH_INTERVAL_SECONDS = int(os.environ.get("NYAARR_DOWNLOAD_QUEUE_REFRESH_INTERVAL_SECONDS", "5"))
TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS = int(os.environ.get("NYAARR_TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", str(PERIODIC_MAINTENANCE_INTERVAL_SECONDS)))
TORRENT_DISPATCH_RETRY_SECONDS = int(os.environ.get("NYAARR_TORRENT_DISPATCH_RETRY_SECONDS", str(5 * 60)))
TORRENT_SUBMISSION_VISIBILITY_GRACE_SECONDS = int(
    os.environ.get("NYAARR_TORRENT_SUBMISSION_VISIBILITY_GRACE_SECONDS", "90")
)
MAX_TORRENT_SEARCHES_PER_TICK = int(os.environ.get("NYAARR_MAX_TORRENT_SEARCHES_PER_TICK", "10"))
MAX_TORRENT_DISPATCHES_PER_ANIME_TICK = max(
    1, int(os.environ.get("NYAARR_MAX_TORRENT_DISPATCHES_PER_ANIME_TICK", "4"))
)
MAX_TORRENT_DISPATCH_ANIME_PER_TICK = max(
    1, int(os.environ.get("NYAARR_MAX_TORRENT_DISPATCH_ANIME_PER_TICK", "2"))
)
MAX_STORAGE_REPAIRS_PER_TICK = max(1, int(os.environ.get("NYAARR_MAX_STORAGE_REPAIRS_PER_TICK", "20")))
MAX_AIRING_REFRESHES_PER_TICK = int(os.environ.get("NYAARR_MAX_AIRING_REFRESHES_PER_TICK", "10"))
MAX_POSTER_REPAIRS_PER_TICK = int(os.environ.get("NYAARR_MAX_POSTER_REPAIRS_PER_TICK", "3"))
MAX_ANILIST_METADATA_REFRESHES_PER_TICK = int(os.environ.get("NYAARR_MAX_ANILIST_METADATA_REFRESHES_PER_TICK", "3"))
POSTER_CHECK_MAX_AGE_SECONDS = int(os.environ.get("NYAARR_POSTER_CHECK_MAX_AGE_SECONDS", str(24 * 60 * 60)))
ANILIST_METADATA_REFRESH_MAX_AGE_SECONDS = int(os.environ.get("NYAARR_ANILIST_METADATA_REFRESH_MAX_AGE_SECONDS", str(24 * 60 * 60)))
JIKAN_ONGOING_TITLE_REFRESH_MAX_AGE_SECONDS = int(
    os.environ.get("NYAARR_JIKAN_ONGOING_TITLE_REFRESH_MAX_AGE_SECONDS", str(6 * 60 * 60))
)
JIKAN_FINISHED_TITLE_REFRESH_MAX_AGE_SECONDS = int(
    os.environ.get("NYAARR_JIKAN_FINISHED_TITLE_REFRESH_MAX_AGE_SECONDS", str(30 * 24 * 60 * 60))
)
EXTERNAL_REQUEST_SPACING_SECONDS = float(os.environ.get("NYAARR_EXTERNAL_REQUEST_SPACING_SECONDS", "2.0"))
ROOT_IMPORT_METADATA_ON_SAVE = os.environ.get("NYAARR_ROOT_IMPORT_METADATA_ON_SAVE") == "1"
MAX_IGNORED_TORRENTS = int(os.environ.get("NYAARR_MAX_IGNORED_TORRENTS", "500"))
MAX_UNMONITORED_TITLE_ENTRIES = int(os.environ.get("NYAARR_MAX_UNMONITORED_TITLE_ENTRIES", "500"))
MAX_QUEUE_HISTORY_PER_ANIME = int(os.environ.get("NYAARR_MAX_QUEUE_HISTORY_PER_ANIME", "75"))
MAX_METADATA_CANDIDATES_PER_ANIME = int(os.environ.get("NYAARR_MAX_METADATA_CANDIDATES_PER_ANIME", "10"))
MAX_FLAGGED_FILES_PER_QUEUE = int(os.environ.get("NYAARR_MAX_FLAGGED_FILES_PER_QUEUE", "25"))
MAX_SELECTED_FILES_PER_QUEUE = int(os.environ.get("NYAARR_MAX_SELECTED_FILES_PER_QUEUE", "100"))
MAX_RESOLVED_METADATA_CACHE_ENTRIES = int(os.environ.get("NYAARR_MAX_RESOLVED_METADATA_CACHE_ENTRIES", "2000"))
_STATE_MAINTENANCE_LOCK = threading.Lock()
_EXTERNAL_MAINTENANCE_LOCK = threading.Lock()
_USER_DATABASE_LOCK = threading.RLock()
_ROOT_SCAN_PROGRESS_LOCK = threading.Lock()
_ROOT_SCAN_JOB_LOCK = threading.Lock()
_ROOT_SCAN_THREAD: threading.Thread | None = None
_STATE_REPOSITORIES: dict[tuple[str, str], SQLiteStateRepository] = {}
_AIRING_REPOSITORIES: dict[str, SQLiteAiringRepository] = {}
_EPISODE_TITLE_REPOSITORIES: dict[str, SQLiteEpisodeTitleRepository] = {}
_ROOT_SCAN_PROGRESS: dict[str, Any] = {
    "active": False,
    "phase": "Idle",
    "current": 0,
    "total": 0,
    "percent": 0,
    "message": "",
    "summary": _empty_scan_summary() if "_empty_scan_summary" in globals() else {},
    "started_at": "",
    "completed_at": "",
}
DOWNLOAD_CLIENT_TIMEOUT_SECONDS = 10
RELEASE_SPEC_TOKENS = {
    "10bit",
    "10-bit",
    "12bit",
    "12-bit",
    "2ch",
    "5.1",
    "7.1",
    "aac",
    "aac2",
    "aac2.0",
    "ac3",
    "amzn",
    "atvp",
    "av1",
    "bd",
    "bdmv",
    "bdrip",
    "bdrips",
    "bluray",
    "blu-ray",
    "cr",
    "crunchyroll",
    "dd",
    "dd+",
    "ddp",
    "ddp2",
    "ddp2.0",
    "ddp5",
    "ddp5.1",
    "dual",
    "dual-audio",
    "dual audio",
    "eac3",
    "ember",
    "eng",
    "english",
    "flac",
    "freehold",
    "hevc",
    "h264",
    "h.264",
    "h265",
    "h.265",
    "hdtv",
    "hidive",
    "hi10p",
    "multi",
    "multi-audio",
    "multi-subs",
    "opus",
    "proper",
    "repack",
    "sub",
    "subbed",
    "subs",
    "truehd",
    "v2",
    "v3",
    "v4",
    "web",
    "web-dl",
    "webdl",
    "webrip",
    "x264",
    "x265",
}
RELEASE_SPEC_PATTERNS = (
    r"\b(?:480p|540p|576p|720p|810p|900p|1080p|1440p|2160p|4k|8k)\b",
    r"\b(?:x|h\.?)26[45]\b",
    r"\b(?:aac|ddp?|eac3|ac3|flac|opus|truehd)(?:\d(?:\.\d)?)?\b",
    r"\b(?:web[-\s]?dl|web[-\s]?rip|blu[-\s]?ray|bd[-\s]?rip|hdtv|remux)\b",
    r"\b(?:dual[-\s]?audio|multi[-\s]?(?:audio|subs?)|eng(?:lish)?[-\s]?subs?)\b",
    r"\b(?:hevc|av1|hi10p|10[-\s]?bit|12[-\s]?bit)\b",
    r"\b(?:batch|complete|repack|proper|v\d)\b",
    r"\b(?:cr|amzn|nf|netflix|dsnp|hidive|b-global|bilibili)\b",
    r"\[[a-f0-9]{8}\]",
)


def anime_library() -> list[dict[str, Any]]:
    return _read_user_database()["anime"]


def dashboard_model(database: dict[str, Any] | None = None) -> dict[str, Any]:
    database = database if database is not None else _read_user_database()
    library = database["anime"]
    manual_items, manual_changed = _manual_selection_items(database)
    if manual_changed:
        _write_user_database(database)
    queued_rows = _activity_queued_rows(database)
    history_rows = _activity_history_rows(database)
    blocked_rows = _activity_blocked_rows(database)
    missing_settings = missing_settings_summary(database)
    setup_steps = _dashboard_setup_steps(database, len(library), missing_settings)
    attention_items = _dashboard_attention_items(
        missing_settings,
        manual_count=len(manual_items),
        metadata_count=_metadata_verification_count(library),
        queued_count=len(queued_rows),
        blocked_count=len(blocked_rows),
    )
    return {
        "setup_steps": setup_steps,
        "setup_complete": all(step["complete"] for step in setup_steps),
        "attention_items": attention_items,
        "active_downloads": queued_rows[:5],
        "recent_history": history_rows[:5],
        "recent_anime": _recent_dashboard_anime(library),
        "counts": {
            "attention": len(attention_items),
            "active": len(queued_rows),
            "manual": len(manual_items),
            "metadata": _metadata_verification_count(library),
            "blocked": len(blocked_rows),
        },
    }


def dashboard_page_model() -> dict[str, Any]:
    database = _read_user_database()
    library = database['anime']
    return {
        'anime_cards': library,
        'stats': library_stats(library),
        'dashboard': dashboard_model(database),
        'revision': int(database.get(REVISION_FIELD) or 0),
    }


def anime_list_page_model() -> dict[str, Any]:
    database = _read_user_database()
    return {
        'anime_cards': database['anime'],
        'revision': int(database.get(REVISION_FIELD) or 0),
    }


def ui_bootstrap_model() -> dict[str, Any]:
    database = _read_user_database()
    from .maintenance import job_status_summary

    return {
        'revision': int(database.get(REVISION_FIELD) or 0),
        'sidebar_counts': sidebar_counts(database),
        'missing_settings': missing_settings_summary(database),
        'root_scan': root_folder_scan_progress(),
        'jobs': job_status_summary(),
    }


def _dashboard_setup_steps(database: dict[str, Any], anime_count: int, missing_settings: dict[str, Any]) -> list[dict[str, Any]]:
    settings = database.get("settings") if isinstance(database.get("settings"), dict) else {}
    download_client = settings.get("download_client") if isinstance(settings, dict) else {}
    preferred_subbers = _preferred_subber_list(database)
    missing = set(missing_settings.get("missing") if isinstance(missing_settings.get("missing"), list) else [])
    return [
        {
            "label": "Choose anime root folder",
            "description": "Nyaarr needs a library folder before it can place downloads or scan local files.",
            "complete": "root_folder" not in missing,
            "action_label": "Open settings",
            "action_url": "/settings",
        },
        {
            "label": "Connect qBittorrent",
            "description": "A download client is required before selected releases can be queued.",
            "complete": "download_client" not in missing and isinstance(download_client, dict) and download_client.get("enabled"),
            "action_label": "Connect client",
            "action_url": "/settings",
        },
        {
            "label": "Confirm preferred subbers",
            "description": "Preferred release groups guide automatic RSS searches and dispatch decisions.",
            "complete": bool(preferred_subbers),
            "action_label": "Review preferences",
            "action_url": "/settings",
        },
        {
            "label": "Add or import anime",
            "description": "Add a title from metadata search or scan your root folder to start monitoring.",
            "complete": anime_count > 0,
            "action_label": "Add anime",
            "action_url": "/add",
        },
    ]


def _dashboard_attention_items(
    missing_settings: dict[str, Any],
    *,
    manual_count: int,
    metadata_count: int,
    queued_count: int,
    blocked_count: int,
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    missing_count = int(missing_settings.get("count") or 0)
    if missing_count:
        items.append({
            "tone": "yellow",
            "label": "Setup incomplete",
            "value": str(missing_count),
            "description": "Required settings are missing.",
            "action_label": "Fix settings",
            "action_url": "/settings",
        })
    if manual_count:
        items.append({
            "tone": "yellow",
            "label": "Torrent decisions",
            "value": str(manual_count),
            "description": "Low-confidence releases need a manual choice.",
            "action_label": "Review",
            "action_url": "/anime/manual-selection",
        })
    if metadata_count:
        items.append({
            "tone": "yellow",
            "label": "Metadata review",
            "value": str(metadata_count),
            "description": "Root-folder imports need the right anime match.",
            "action_label": "Match metadata",
            "action_url": "/anime/metadata-verification",
        })
    if blocked_count:
        items.append({
            "tone": "red",
            "label": "Blocked torrents",
            "value": str(blocked_count),
            "description": "Rejected candidates are being kept out of automation.",
            "action_label": "View blocked",
            "action_url": "/activity/blocked",
        })
    if queued_count:
        items.append({
            "tone": "blue",
            "label": "Active downloads",
            "value": str(queued_count),
            "description": "Downloads are queued, checking, or in progress.",
            "action_label": "Open activity",
            "action_url": "/activity",
        })
    return items


def _recent_dashboard_anime(library: list[dict[str, Any]], limit: int = 6) -> list[dict[str, str]]:
    rows = []
    for anime in reversed(library[-limit:]):
        if not isinstance(anime, dict):
            continue
        rows.append(
            {
                "library_id": str(anime.get("library_id") or ""),
                "title": str(anime.get("title") or anime.get("original_title") or "Unknown"),
                "state": str(anime.get("library_state") or "Unknown"),
                "poster": str(anime.get("poster") or anime.get("poster_url") or ""),
            }
        )
    return rows


def run_startup_download_status_check() -> dict[str, Any]:
    if not _STATE_MAINTENANCE_LOCK.acquire(blocking=False):
        return {"status": "skipped", "reason": "maintenance already running"}

    summary = {
        "status": "ok",
        "queue_refreshed": False,
        "library_refreshed": False,
        "dispatch_attempts": 0,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        database = _read_user_database()
        changed = False

        if _refresh_download_queue(database):
            summary["queue_refreshed"] = True
            changed = True

        before_library = json.dumps(database["anime"], sort_keys=True, default=str)
        _refresh_library_states(database["anime"], root_folder_configured=_root_folder_configured(database))
        if before_library != json.dumps(database["anime"], sort_keys=True, default=str):
            summary["library_refreshed"] = True
            changed = True

        now = time.time()
        for anime in database.get("anime", []):
            if summary["dispatch_attempts"] >= MAX_TORRENT_DISPATCH_ANIME_PER_TICK:
                break
            if not isinstance(anime, dict) or not _should_attempt_periodic_dispatch(database, anime, now):
                continue
            anime["torrent_dispatch_attempted_at"] = datetime.now(timezone.utc).isoformat()
            _maybe_dispatch_torrent(database, anime)
            summary["dispatch_attempts"] += 1
            changed = True

        if changed:
            _record_event(
                database,
                "system",
                "Startup torrent status check completed: "
                f"queue_refreshed={summary['queue_refreshed']}, "
                f"library_refreshed={summary['library_refreshed']}, "
                f"dispatch_attempts={summary['dispatch_attempts']}."
            )
            _write_user_database(database)
    finally:
        _STATE_MAINTENANCE_LOCK.release()
    return summary


def run_download_queue_refresh() -> dict[str, Any]:
    """Refresh qBittorrent-backed queue state without running broader maintenance."""
    if not _STATE_MAINTENANCE_LOCK.acquire(blocking=False):
        return {"status": "skipped", "reason": "maintenance already running"}

    summary = {
        "status": "ok",
        "queue_refreshed": False,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        database = _read_user_database()
        if _refresh_download_queue(database):
            summary["queue_refreshed"] = True
            _write_user_database(database)
    finally:
        _STATE_MAINTENANCE_LOCK.release()
    return summary


def run_periodic_maintenance_tick(
    *, include_airing: bool = True, include_external: bool = True, include_local: bool = True
) -> dict[str, Any]:
    maintenance_lock = _STATE_MAINTENANCE_LOCK if include_local else _EXTERNAL_MAINTENANCE_LOCK
    if not maintenance_lock.acquire(blocking=False):
        return {"status": "skipped", "reason": "maintenance already running"}

    summary: dict[str, Any] = {
        "status": "ok",
        "queue_refreshed": False,
        "library_refreshed": False,
        "torrent_searches": 0,
        "dispatch_attempts": 0,
        "external_limited": False,
        "external_request_spacing_seconds": EXTERNAL_REQUEST_SPACING_SECONDS,
        "max_torrent_searches": MAX_TORRENT_SEARCHES_PER_TICK,
        "max_airing_refreshes": MAX_AIRING_REFRESHES_PER_TICK,
        "external_enabled": include_external,
        "torrent_searches_deferred": 0,
        "airing_refreshes_deferred": 0,
        "poster_repairs": 0,
        "poster_repairs_deferred": 0,
        "anilist_metadata_refreshes": 0,
        "anilist_metadata_deferred": 0,
        "nfo_files_written": 0,
        "nested_files_flattened": 0,
        "stale_torrents_removed": 0,
        "missing_torrents_restarted": 0,
        "last_external_request_at": None,
        "next_external_request_after": None,
        "last_run_at": datetime.now(timezone.utc).isoformat(),
        "airing": None,
    }
    try:
        database = _read_user_database()
        changed = False
        now = time.time()

        if include_local:
            storage_summary = _reconcile_library_storage_and_missing_torrents(database)
            summary.update(storage_summary)
            if any(storage_summary.values()):
                changed = True

        if include_local and _refresh_download_queue(database):
            summary["queue_refreshed"] = True
            changed = True

        before_library = json.dumps(database["anime"], sort_keys=True, default=str)
        if include_local:
            _refresh_library_states(database["anime"], root_folder_configured=_root_folder_configured(database))
        if before_library != json.dumps(database["anime"], sort_keys=True, default=str):
            summary["library_refreshed"] = True
            changed = True

        external_request_count = 0
        for anime in database.get("anime", []):
            if not isinstance(anime, dict):
                continue
            if _normalize_unusable_torrent_candidates(database, anime):
                changed = True
            if include_external and _should_refresh_torrent_search(anime, now):
                if summary["torrent_searches"] >= MAX_TORRENT_SEARCHES_PER_TICK:
                    summary["torrent_searches_deferred"] += 1
                    summary["external_limited"] = True
                else:
                    _pace_external_request(external_request_count)
                    _refresh_torrent_search(anime, database)
                    external_request_count += 1
                    summary["last_external_request_at"] = datetime.now(timezone.utc).isoformat()
                    summary["torrent_searches"] += 1
                    changed = True
            elif not include_external and _should_refresh_torrent_search(anime, now):
                summary["torrent_searches_deferred"] += 1
            if (include_local or include_external) and _should_attempt_periodic_dispatch(database, anime, now):
                if summary["dispatch_attempts"] >= MAX_TORRENT_DISPATCH_ANIME_PER_TICK:
                    continue
                anime["torrent_dispatch_attempted_at"] = datetime.now(timezone.utc).isoformat()
                _maybe_dispatch_torrent(database, anime)
                summary["dispatch_attempts"] += 1
                changed = True
            if include_local and _sync_anime_nfo_file(anime):
                summary["nfo_files_written"] = int(summary.get("nfo_files_written") or 0) + 1
            if include_external and _should_repair_poster(anime, now):
                if summary["poster_repairs"] >= MAX_POSTER_REPAIRS_PER_TICK:
                    summary["poster_repairs_deferred"] += 1
                    summary["external_limited"] = True
                else:
                    _pace_external_request(external_request_count)
                    external_request_count += 1
                    if _repair_anime_poster(database, anime):
                        changed = True
                    summary["poster_repairs"] += 1
                    summary["last_external_request_at"] = datetime.now(timezone.utc).isoformat()
            elif not include_external and _should_repair_poster(anime, now):
                summary["poster_repairs_deferred"] += 1

        if changed:
            _record_event(
                database,
                "system",
                "Maintenance tick completed: "
                f"queue_refreshed={summary['queue_refreshed']}, "
                f"library_refreshed={summary['library_refreshed']}, "
                f"torrent_searches={summary['torrent_searches']}, "
                f"dispatch_attempts={summary['dispatch_attempts']}, "
                f"poster_repairs={summary['poster_repairs']}, "
                f"anilist_metadata_refreshes={summary['anilist_metadata_refreshes']}."
            )
            _write_user_database(database)
    finally:
        maintenance_lock.release()

    if include_airing and include_external:
        summary["airing"] = refresh_library_anilist_state(force=False, max_checked=MAX_AIRING_REFRESHES_PER_TICK)
        summary["airing_refreshes_deferred"] = int(summary["airing"].get("deferred", 0))
        summary["anilist_metadata_refreshes"] = int(summary["airing"].get("checked", 0))
        summary["anilist_metadata_deferred"] = int(summary["airing"].get("deferred", 0))
    return summary


def _pace_external_request(request_count: int) -> None:
    return None


def _reconcile_library_storage_and_missing_torrents(database: dict[str, Any]) -> dict[str, int]:
    summary = {"nested_files_flattened": 0, "stale_torrents_removed": 0, "missing_torrents_restarted": 0}
    budget = MAX_STORAGE_REPAIRS_PER_TICK
    library = [anime for anime in database.get("anime", []) if isinstance(anime, dict)]

    for anime in library:
        if budget <= 0:
            break
        root_text = _existing_anime_local_path(anime)
        root = Path(root_text) if root_text else None
        if root is None or not root.exists() or not root.is_dir():
            continue
        # Discovery is read-only. Nested torrent content and directories remain
        # untouched so qBittorrent can continue to own and seed their paths.
        anime["episode_files"] = sorted((str(path.resolve()) for path in _media_files(root)), key=str.casefold)
        _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))

    # Storage maintenance is deliberately library-only. Automatic qBittorrent
    # relocation, removal, and restart are forbidden because stale client paths
    # are not reliable evidence of where payload data belongs. Those actions
    # require an explicit, reviewed recovery operation.
    return summary


def _client_torrent_matches_anime(torrent: dict[str, Any], anime: dict[str, Any]) -> bool:
    library_id = str(anime.get("library_id") or "").casefold()
    tags = {tag.strip().casefold() for tag in str(torrent.get("tags") or "").split(",") if tag.strip()}
    if library_id and library_id in tags:
        return True
    name = str(torrent.get("name") or "")
    return any(torrent_title_matches(title, name) for _source, title in _anime_confidence_title_values(anime))


def _remove_empty_nested_directories(root: Path) -> None:
    directories = sorted((path for path in root.rglob("*") if path.is_dir()), key=lambda path: len(path.parts), reverse=True)
    for directory in directories:
        try:
            directory.rmdir()
        except OSError:
            continue


def _normalize_torrent_search_state(anime: dict[str, Any]) -> None:
    if _download_need_satisfied(anime):
        _mark_torrent_search_not_needed(anime)


def _mark_torrent_search_not_needed(anime: dict[str, Any]) -> None:
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "No torrent search needed",
        "candidates": [],
        "notices": [],
    }
    anime["torrent_manual_selection"] = {"required": False}


def _mark_torrent_search_pending(anime: dict[str, Any]) -> None:
    if anime.get("monitored") is False:
        _clear_download_plan_for_unmonitored(anime)
        return
    if _download_need_satisfied(anime):
        _mark_torrent_search_not_needed(anime)
        return
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    if torrent_search.get("candidates"):
        return
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "Queued for background torrent search",
        "candidates": [],
        "notices": ["Torrent search will run in the background maintenance worker."],
    }


def _download_need_satisfied(anime: dict[str, Any]) -> bool:
    if anime.get("library_state") == "Completed":
        return True
    completion = anime.get("completion") if isinstance(anime.get("completion"), dict) else {}
    if completion and int(completion.get("missing_episodes") or 0) <= 0:
        return True
    expected_episodes = _expected_episode_count(anime)
    return expected_episodes is not None and _local_episode_count(anime) >= expected_episodes


def _refresh_torrent_search(anime: dict[str, Any], database: dict[str, Any] | None = None) -> None:
    torrent_search = find_torrents_for_anime(anime, _preferred_subber_list(database or {}))
    torrent_search["checked_at"] = datetime.now(timezone.utc).isoformat()
    anime["torrent_search"] = torrent_search
    if database is not None:
        _normalize_unusable_torrent_candidates(database, anime, refreshed=True)
        candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
        candidate_count = len(candidates)
        if candidate_count > 0:
            anime["torrent_manual_selection"] = {"required": False}
        query = str(torrent_search.get("query") or anime.get("title") or anime.get("original_title") or "anime")
        _record_event(database, "nyaa", f"Refreshed Nyaa search for {query}; {candidate_count} usable candidate(s) available.", anime)


def _filter_ignored_torrent_candidates(database: dict[str, Any], candidates: list[Any]) -> list[dict[str, Any]]:
    ignored_keys = _ignored_torrent_keys(database)
    return [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict)
        and not _is_dub_release(candidate)
        and _torrent_ignore_key(candidate) not in ignored_keys
    ]


def _set_no_usable_torrent_candidates(anime: dict[str, Any]) -> None:
    _set_manual_selection_required(
        anime,
        0,
        "No usable torrent candidates were found. Manual torrent or magnet link is required.",
        "",
        intervention_type="no_candidates",
    )


def _normalize_unusable_torrent_candidates(database: dict[str, Any], anime: dict[str, Any], *, refreshed: bool = False) -> bool:
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    raw_candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    if not raw_candidates:
        if refreshed and _missing_episode_numbers(anime):
            _set_no_usable_torrent_candidates(anime)
            return True
        return False

    candidates = _filter_ignored_torrent_candidates(database, raw_candidates)
    if len(candidates) == len(raw_candidates):
        return False

    torrent_search["candidates"] = candidates
    if not candidates:
        notices = torrent_search.setdefault("notices", [])
        if isinstance(notices, list) and "All refreshed torrent candidates were already blocked or rejected." not in notices:
            notices.append("All refreshed torrent candidates were already blocked or rejected.")
        if _missing_episode_numbers(anime):
            _set_no_usable_torrent_candidates(anime)
    return True


def _should_refresh_torrent_search(anime: dict[str, Any], now: float) -> bool:
    if anime.get("monitored") is False:
        return False
    if _download_need_satisfied(anime):
        return False
    completion = anime.get("completion") if isinstance(anime.get("completion"), dict) else {}
    if int(completion.get("missing_episodes") or 0) <= 0:
        return False
    manual = anime.get("torrent_manual_selection") if isinstance(anime.get("torrent_manual_selection"), dict) else {}
    if _manual_selection_required(anime) and str(manual.get("intervention_type") or "") != "no_candidates":
        return False
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    checked_at = _parse_checked_at(torrent_search.get("checked_at"))
    if checked_at is not None and now - checked_at < TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS:
        return False
    return True


def _should_prefer_provider_poster(anime: dict[str, Any]) -> bool:
    current_poster = str(anime.get("poster") or "").strip()
    if not current_poster:
        return True
    poster_source = str(anime.get("poster_source") or "").strip().casefold()
    if not poster_source or poster_source == "anilist":
        return False
    return str(anime.get("poster_status") or "").strip().casefold() not in {"ok", "repaired"}


def _apply_poster_replacement(database: dict[str, Any], anime: dict[str, Any], replacement: dict[str, Any]) -> bool:
    anime["poster"] = str(replacement.get("poster") or "")
    anime["poster_source"] = _metadata_source_name(replacement)
    _merge_provider_ids(anime, replacement)
    anime["poster_checked_at"] = datetime.now(timezone.utc).isoformat()
    anime["poster_status"] = "repaired"
    anime.pop("poster_error", None)
    _record_event(
        database,
        "metadata",
        f"Repaired poster for {anime.get('title', 'anime')} from {anime['poster_source']}.",
        anime,
    )
    return True


def _should_attempt_periodic_dispatch(database: dict[str, Any], anime: dict[str, Any], now: float) -> bool:
    if anime.get("monitored") is False:
        return False
    completion = anime.get("completion") if isinstance(anime.get("completion"), dict) else {}
    if int(completion.get("missing_episodes") or 0) <= 0:
        return False
    if _manual_selection_required(anime):
        return False
    if _recent_dispatch_attempt(anime, now):
        return False
    if not _root_folder_configured(database):
        return False
    client_settings = database.get("settings", {}).get("download_client")
    if not isinstance(client_settings, dict):
        return False
    if client_settings.get("implementation") != "qbittorrent" or not client_settings.get("enabled"):
        return False
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    return bool(_filter_ignored_torrent_candidates(database, candidates))


def _should_repair_poster(anime: dict[str, Any], now: float) -> bool:
    checked_at = _parse_checked_at(anime.get("poster_checked_at"))
    if checked_at is not None and now - checked_at < POSTER_CHECK_MAX_AGE_SECONDS:
        return False
    return bool(_poster_repair_titles(anime))


def _repair_anime_poster(database: dict[str, Any], anime: dict[str, Any]) -> bool:
    current_poster = str(anime.get("poster") or "").strip()
    if _should_prefer_provider_poster(anime):
        replacement = _alternate_poster_metadata(anime)
        if replacement is not None:
            return _apply_poster_replacement(database, anime, replacement)

    if current_poster and _poster_url_accessible(current_poster):
        anime["poster_checked_at"] = datetime.now(timezone.utc).isoformat()
        anime["poster_status"] = "ok"
        return True

    replacement = _alternate_poster_metadata(anime)
    anime["poster_checked_at"] = datetime.now(timezone.utc).isoformat()
    if replacement is None:
        anime["poster_status"] = "unresolved"
        if current_poster:
            anime["poster_error"] = "Stored poster URL could not be loaded and no alternate provider poster matched."
        return True

    return _apply_poster_replacement(database, anime, replacement)


def _should_refresh_anilist_metadata(anime: dict[str, Any], now: float) -> bool:
    if not _anilist_metadata_search_titles(anime):
        return False
    if _anilist_reconciliation_pending(anime) and _parse_checked_at(anime.get("anilist_metadata_checked_at")) is None:
        return True
    checked_at = _parse_checked_at(anime.get("anilist_metadata_checked_at"))
    if checked_at is not None and now - checked_at < ANILIST_METADATA_REFRESH_MAX_AGE_SECONDS:
        return False
    return True


def _refresh_anilist_metadata(database: dict[str, Any], anime: dict[str, Any], now: float) -> bool:
    match_context = _anilist_metadata_match_context(anime)
    if not match_context["search_titles"]:
        _mark_anilist_metadata_checked(anime, now, "No title available for AniList metadata refresh.")
        return True

    try:
        match = _anilist_metadata_match(anime, match_context)
    except MetadataProviderError as exc:
        _mark_anilist_metadata_checked(anime, now, str(exc))
        _mark_anilist_reconciliation_pending(anime, str(exc))
        return True

    if match is None:
        _mark_anilist_metadata_checked(anime, now, "No confident AniList metadata match was found.")
        _mark_anilist_reconciliation_pending(anime, "No confident AniList metadata match was found.")
        return True

    _resolved_metadata_cache_store(match_context, match)
    anime.setdefault("torrent_search", {"candidates": [], "notices": []})
    _apply_resolved_metadata(anime, match, match_context["search_titles"], "anilist-routine")
    anime["anilist_metadata_checked_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    anime.pop("anilist_metadata_error", None)
    _mark_anilist_reconciliation_resolved(anime)
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    _sync_anime_nfo_file(anime)
    _record_event(database, "metadata", f"Updated {anime.get('title', 'anime')} metadata from AniList.", anime)
    return True


def _anilist_metadata_match(anime: dict[str, Any], match_context: dict[str, Any]) -> dict[str, Any] | None:
    anilist_id = _provider_id_value(anime, "anilist") or _anilist_id_from_poster_url(anime.get("poster"))
    if anilist_id:
        match = search_anilist_by_id(anilist_id)
        return match if _metadata_episode_count_compatible(match_context, match) else None

    results: list[dict[str, Any]] = []
    seen = set()
    for title in match_context["search_titles"]:
        for result in search_anilist(title):
            result_key = _metadata_result_key(result)
            if result_key in seen:
                continue
            seen.add(result_key)
            results.append(result)
    return _best_metadata_match(match_context, results)


def _anilist_metadata_match_context(anime: dict[str, Any]) -> dict[str, Any]:
    titles = _anilist_metadata_search_titles(anime)
    context = _metadata_match_context(titles[0] if titles else "")
    context["search_titles"] = titles
    context["year"] = _year_value(anime.get("year"))
    context["season_number"] = _season_hint_value(anime.get("season_number"))
    context["local_episode_count"] = _local_episode_count(anime)
    return context


def _anilist_metadata_search_titles(anime: dict[str, Any]) -> list[str]:
    values: list[Any] = [anime.get("title"), anime.get("original_title")]
    search_titles = anime.get("metadata_search_titles")
    if isinstance(search_titles, list):
        values.extend(search_titles)
    aliases = anime.get("aliases")
    if isinstance(aliases, list):
        values.extend(aliases[:8])

    titles = []
    seen = set()
    for value in values:
        title = str(value or "").strip()
        key = title.casefold()
        if title and title != "Unknown" and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


def _mark_anilist_metadata_checked(anime: dict[str, Any], now: float, error: str) -> None:
    anime["anilist_metadata_checked_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    if error:
        anime["anilist_metadata_error"] = error
    else:
        anime.pop("anilist_metadata_error", None)

def _alternate_poster_metadata(anime: dict[str, Any]) -> dict[str, Any] | None:
    provider_ids = anime.get("provider_ids") if isinstance(anime.get("provider_ids"), dict) else {}
    anilist_id = provider_ids.get("anilist")
    if anilist_id:
        try:
            result = search_anilist_by_id(anilist_id)
        except MetadataProviderError:
            result = None
        if _metadata_has_usable_poster(result):
            return result

    match_context = _metadata_match_context(_poster_repair_titles(anime)[0])
    match_context["year"] = _year_value(anime.get("year"))
    match_context["season_number"] = _season_hint_value(anime.get("season_number"))
    for search_function in (search_anilist, search_kitsu, search_tmdb):
        for title in _poster_repair_titles(anime):
            try:
                results = search_function(title)
            except MetadataProviderError:
                continue
            poster_results = [result for result in results if _metadata_has_usable_poster(result)]
            match = _best_metadata_match(match_context, poster_results)
            if match is not None:
                return match
    return None


def _enrich_metadata_poster_from_candidates(
    match_context: dict[str, Any],
    match: dict[str, Any],
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    anilist_id = _provider_id_value({"provider_ids": match.get("provider_ids", {})}, "anilist")
    if anilist_id and _metadata_source_name(match) != "AniList":
        try:
            anilist_match = search_anilist_by_id(anilist_id)
        except MetadataProviderError:
            anilist_match = None
        if _metadata_has_usable_poster(anilist_match):
            enriched = dict(match)
            enriched["poster"] = str(anilist_match.get("poster") or "")
            enriched["poster_source"] = "AniList"
            _merge_provider_ids(enriched, anilist_match)
            return enriched
    if _metadata_has_usable_poster(match):
        return match
    poster_candidates = [candidate for candidate in candidates if _metadata_has_usable_poster(candidate)]
    poster_match = _best_metadata_match(match_context, poster_candidates)
    if poster_match is None:
        return match
    enriched = dict(match)
    enriched["poster"] = str(poster_match.get("poster") or "")
    enriched["poster_source"] = _metadata_source_name(poster_match)
    return enriched

def _anilist_reconciliation_pending(anime: dict[str, Any]) -> bool:
    return str(anime.get("anilist_reconciliation_status") or "").casefold() == "pending"


def _mark_anilist_reconciliation_pending(anime: dict[str, Any], reason: str = "") -> None:
    anime["anilist_reconciliation_status"] = "pending"
    if reason:
        anime["anilist_reconciliation_reason"] = reason


def _mark_anilist_reconciliation_resolved(anime: dict[str, Any]) -> None:
    anime["anilist_reconciliation_status"] = "reconciled"
    anime["anilist_reconciliation_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    anime.pop("anilist_reconciliation_reason", None)


def _mark_anilist_reconciliation_for_current_metadata(anime: dict[str, Any]) -> None:
    if _metadata_source_name(anime) == "AniList" and _provider_id_value(anime, "anilist"):
        _mark_anilist_reconciliation_resolved(anime)
        return
    if not anime.get("manual_verification_required"):
        _mark_anilist_reconciliation_pending(anime, "Final AniList reconciliation is pending.")
        anime.pop("anilist_metadata_checked_at", None)


def _mark_anilist_reconciliation_for_match(anime: dict[str, Any], match: dict[str, Any]) -> None:
    if _metadata_source_name(match) == "AniList" and _provider_id_value({"provider_ids": match.get("provider_ids", {})}, "anilist"):
        _mark_anilist_reconciliation_resolved(anime)
        anime["anilist_metadata_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        return
    _mark_anilist_reconciliation_pending(anime, f"Resolved from {_metadata_source_name(match)}; final AniList reconciliation is pending.")
    anime.pop("anilist_metadata_checked_at", None)


def _metadata_has_usable_poster(metadata: Any) -> bool:
    return isinstance(metadata, dict) and bool(str(metadata.get("poster") or "").strip())


def _poster_repair_titles(anime: dict[str, Any]) -> list[str]:
    values: list[Any] = [anime.get("title"), anime.get("original_title")]
    search_titles = anime.get("metadata_search_titles")
    if isinstance(search_titles, list):
        values.extend(search_titles)
    aliases = anime.get("aliases")
    if isinstance(aliases, list):
        values.extend(aliases[:5])
    titles = []
    seen = set()
    for value in values:
        title = str(value or "").strip()
        key = title.casefold()
        if title and title != "Unknown" and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles


def _poster_url_accessible(url: str) -> bool:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "nyaarr/0.1", "Accept": "image/*,*/*;q=0.8"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS) as response:
            content_type = str(response.headers.get("content-type") or "").casefold()
            return response.status < 400 and (not content_type or content_type.startswith("image/"))
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError):
        return False


def _recent_dispatch_attempt(anime: dict[str, Any], now: float) -> bool:
    if anime.get("torrent_dispatch_backlog"):
        return False
    attempted_at = _parse_checked_at(anime.get("torrent_dispatch_attempted_at"))
    return attempted_at is not None and now - attempted_at < TORRENT_DISPATCH_RETRY_SECONDS


def user_settings() -> dict[str, Any]:
    database = _read_user_database()
    saved_settings = database.get("settings") if isinstance(database, dict) else {}
    settings = dict(saved_settings) if isinstance(saved_settings, dict) else {}
    settings.setdefault("download_client", _empty_download_client_settings())
    settings["preferred_subbers"] = _normalized_preferred_subbers(settings.get("preferred_subbers"))
    settings["preferred_subbers_text"] = "\n".join(settings["preferred_subbers"])
    settings["torrent_confidence_threshold"] = _torrent_confidence_threshold({"settings": settings})
    settings["timezone"] = _settings_timezone_value(settings.get("timezone"))
    settings["timezone_label"] = settings["timezone"]
    settings["timezone_options"] = display_timezone_options()
    return settings


def display_timezone_options() -> list[dict[str, str]]:
    return [dict(option) for option in DISPLAY_TIMEZONE_OPTIONS]


def display_timezone_label(settings: dict[str, Any] | None = None) -> str:
    return _settings_timezone_value((settings or {}).get("timezone") if isinstance(settings, dict) else None)


def _display_timezone(settings: dict[str, Any] | None = None) -> timezone:
    label = display_timezone_label(settings) if isinstance(settings, dict) else display_timezone_label(user_settings())
    if label == "UTC":
        return timezone.utc
    match = re.fullmatch(r"GMT([+-]\d{1,2})", label)
    if not match:
        return timezone(timedelta(hours=8), DEFAULT_DISPLAY_TIMEZONE)
    return timezone(timedelta(hours=int(match.group(1))), label)


def _display_today(settings: dict[str, Any] | None = None) -> date:
    return datetime.now(_display_timezone(settings)).date()


def _settings_timezone_value(value: Any) -> str:
    selected = str(value or DEFAULT_DISPLAY_TIMEZONE).strip().upper()
    if selected in {"UTC", "GMT", "GMT+0", "GMT-0"}:
        return "UTC"
    match = re.fullmatch(r"(?:GMT)?([+-]?\d{1,2})", selected)
    if match:
        offset = int(match.group(1))
        if -12 <= offset <= 14:
            return "UTC" if offset == 0 else f"GMT{offset:+d}"
    valid_values = {option["value"] for option in DISPLAY_TIMEZONE_OPTIONS}
    return selected if selected in valid_values else DEFAULT_DISPLAY_TIMEZONE


def refresh_library_airing_schedule(force: bool = False, max_checked: int | None = None) -> dict[str, int]:
    database = _read_user_database()
    summary = {"checked": 0, "updated": 0, "skipped": 0, "failed": 0, "deferred": 0}
    changed = False
    now = time.time()

    for anime in database["anime"]:
        before_state = _schedule_snapshot(anime)
        _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))

        if not _should_refresh_airing_schedule(anime, now, force):
            summary["skipped"] += 1
            if before_state != _schedule_snapshot(anime):
                changed = True
            continue

        if max_checked is not None and summary["checked"] >= max_checked:
            summary["deferred"] += 1
            continue

        summary["checked"] += 1
        _pace_external_request(summary["checked"] - 1)
        if _refresh_anime_airing_schedule(anime, now):
            summary["updated"] += 1
        else:
            summary["failed"] += 1
        changed = True

    if changed:
        _write_user_database(database)
    return summary


def refresh_library_anilist_state(force: bool = False, max_checked: int | None = None) -> dict[str, int]:
    database = _read_user_database()
    summary = {"checked": 0, "updated": 0, "skipped": 0, "failed": 0, "deferred": 0}
    changed = False
    now = time.time()
    repository = _airing_repository()
    for anime in database["anime"]:
        anilist_id = _provider_id_value(anime, "anilist") or _anilist_id_from_poster_url(anime.get("poster"))
        if not anilist_id:
            summary["skipped"] += 1
            continue
        if not force and not (
            _should_refresh_airing_schedule(anime, now, False)
            or _should_refresh_anilist_metadata(anime, now)
        ):
            summary["skipped"] += 1
            before_state = _schedule_snapshot(anime)
            _derive_cached_airing_state(anime, now)
            if before_state != _schedule_snapshot(anime):
                changed = True
            continue
        if max_checked is not None and summary["checked"] >= max_checked:
            summary["deferred"] += 1
            continue
        summary["checked"] += 1
        try:
            snapshot = fetch_anilist_snapshot(anilist_id)
        except MetadataRateLimitError:
            raise
        except MetadataProviderError as exc:
            _mark_airing_schedule_checked(anime, now, str(exc))
            summary["failed"] += 1
            changed = True
            continue
        if not snapshot or not isinstance(snapshot.get("media"), dict):
            _mark_airing_schedule_checked(anime, now, "AniList returned no media snapshot.")
            summary["failed"] += 1
            changed = True
            continue
        match = snapshot["media"]
        anime.setdefault("torrent_search", {"candidates": [], "notices": []})
        _apply_resolved_metadata(anime, match, _anilist_metadata_search_titles(anime), "anilist-routine")
        exact_records = [
            record
            for key in ("past_airings", "future_airings")
            for record in snapshot.get(key, [])
            if isinstance(record, dict)
        ]
        repository.upsert(exact_records)
        _store_inferred_historical_airings(anilist_id, repository, now)
        _derive_cached_airing_state(anime, now)
        _ensure_jikan_episode_titles(anime)
        checked_at = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
        anime["airing_schedule_checked_at"] = checked_at
        anime["anilist_metadata_checked_at"] = checked_at
        anime.pop("airing_schedule_error", None)
        anime.pop("anilist_metadata_error", None)
        _sync_anime_nfo_file(anime)
        summary["updated"] += 1
        changed = True
    if changed:
        _write_user_database(database)
    return summary


def _derive_cached_airing_state(anime: dict[str, Any], now: float | None = None) -> None:
    media_id = _provider_id_value(anime, "anilist")
    if not media_id:
        return
    current = time.time() if now is None else now
    records = _airing_repository().for_media(media_id)
    exact = [
        (record, _parse_airing_datetime(record.get("airing_at")))
        for record in records
        if record.get("precision") == "exact"
    ]
    aired = [
        (record, parsed) for record, parsed in exact
        if parsed is not None and parsed.timestamp() <= current
    ]
    future = [
        (record, parsed) for record, parsed in exact
        if parsed is not None and parsed.timestamp() > current
    ]
    if aired:
        anime["aired_episode"] = str(max(int(record["episode"]) for record, _parsed in aired))
    if future:
        record, parsed = min(future, key=lambda item: item[1])
        anime["airing_episode"] = str(record["episode"])
        anime["next_airing_at"] = parsed.isoformat().replace("+00:00", "Z")
        anime["airing_source"] = "AniList"
    elif _is_finished_status(anime.get("status")):
        anime["airing_episode"] = ""
        anime["next_airing_at"] = ""
        anime["airing_source"] = ""
    else:
        previous_next = _parse_airing_datetime(anime.get("next_airing_at"))
        if previous_next is not None and previous_next.timestamp() <= current:
            anime["airing_episode"] = ""
            anime["next_airing_at"] = ""
            anime["airing_source"] = ""
    _refresh_library_state(anime)


def _store_inferred_historical_airings(
    media_id: str,
    repository: SQLiteAiringRepository,
    now: float,
) -> None:
    exact = [
        record for record in repository.for_media(media_id)
        if record.get("precision") == "exact"
    ]
    by_episode = {int(record["episode"]): record for record in exact}
    deltas = []
    for episode in sorted(by_episode):
        following = by_episode.get(episode + 1)
        first_at = _parse_airing_datetime(by_episode[episode].get("airing_at"))
        next_at = _parse_airing_datetime(following.get("airing_at")) if following else None
        if first_at is not None and next_at is not None:
            delta = (next_at - first_at).total_seconds()
            if 5 * 86400 <= delta <= 9 * 86400:
                deltas.append(delta)
    if len(deltas) < 2:
        return
    cadence = median(deltas[-8:])
    stable = [delta for delta in deltas[-8:] if abs(delta - cadence) <= 6 * 3600]
    if len(stable) < max(2, len(deltas[-8:]) * 3 // 4):
        return
    anchor_episode = min(by_episode)
    anchor_at = _parse_airing_datetime(by_episode[anchor_episode].get("airing_at"))
    if anchor_at is None:
        return
    inferred = []
    for episode in range(1, max(by_episode) + 1):
        if episode in by_episode:
            continue
        airing_at = anchor_at + timedelta(seconds=cadence * (episode - anchor_episode))
        if airing_at.timestamp() >= now:
            continue
        inferred.append(
            {
                "provider": "anilist",
                "media_id": media_id,
                "episode": episode,
                "airing_at": airing_at.isoformat().replace("+00:00", "Z"),
                "precision": "estimated",
                "inference_source": f"cadence:{int(cadence)}",
            }
        )
    repository.upsert(inferred)


def calendar_model(view: str = "week", anchor_date: str | None = None) -> dict[str, Any]:
    database = _read_user_database()
    library = database["anime"]
    settings = database.get("settings") if isinstance(database.get("settings"), dict) else {}
    selected_view = view if view in {"week", "month"} else "week"
    anchor = _calendar_anchor_date(anchor_date, settings)
    period_start, period_end = _calendar_period_bounds(selected_view, anchor)
    display_month = anchor.month if selected_view == "month" else None
    repository = _airing_repository()
    media_ids = [_provider_id_value(anime, "anilist") for anime in library]
    media_ids = [media_id for media_id in media_ids if media_id]
    start_utc, end_utc = _calendar_utc_bounds(period_start, period_end, settings)
    records = repository.for_range(
        media_ids,
        start_utc.isoformat().replace("+00:00", "Z"),
        end_utc.isoformat().replace("+00:00", "Z"),
    )
    pending_months = _enqueue_missing_calendar_airing_windows(media_ids, start_utc, end_utc)
    days = _calendar_days(period_start, period_end, library, display_month, settings, records)
    today = _display_today(settings)

    return {
        "view": selected_view,
        "anchor_date": anchor.isoformat(),
        "period_label": _calendar_period_label(selected_view, period_start, period_end),
        "previous_date": _calendar_shift_date(selected_view, anchor, -1).isoformat(),
        "next_date": _calendar_shift_date(selected_view, anchor, 1).isoformat(),
        "today": today.isoformat(),
        "today_label": _display_date_label(today),
        "days": days,
        "scheduled_count": sum(len(day["entries"]) for day in days),
        "airing_count": sum(1 for anime in library if _is_currently_airing(anime)),
        "upcoming_entries": _upcoming_calendar_entries(library, settings=settings),
        "history_pending": bool(pending_months),
        "pending_months": pending_months,
    }


def hydrate_calendar_airing_window(payload: dict[str, Any]) -> None:
    media_ids = [str(value) for value in payload.get("media_ids", []) if str(value or "").isdigit()]
    utc_month = str(payload.get("utc_month") or "")
    page = max(_int_value(payload.get("page")) or 1, 1)
    start_utc, end_utc = _utc_month_bounds(utc_month)
    records, has_next = fetch_anilist_airing_window(
        media_ids,
        int(start_utc.timestamp()),
        int(end_utc.timestamp()),
        page=page,
    )
    _airing_repository().upsert(records)
    chunk_key = hashlib.sha1(",".join(media_ids).encode("utf-8")).hexdigest()[:12]
    if has_next:
        from .maintenance import enqueue_job

        enqueue_job(
            "calendar_airing_window",
            {"media_ids": media_ids, "utc_month": utc_month, "page": page + 1},
            idempotency_key=f"calendar-airing:{utc_month}:{chunk_key}:{page + 1}",
            priority=20,
        )
    else:
        _airing_repository().mark_coverage(media_ids, utc_month)


def hydrate_jikan_episode_titles(payload: dict[str, Any]) -> None:
    mal_id = str(payload.get("mal_id") or "").strip()
    page = max(_int_value(payload.get("page")) or 1, 1)
    if not mal_id.isdigit() or int(mal_id) <= 0:
        raise ValueError("Jikan episode-title job has an invalid MAL ID.")
    repository = _episode_title_repository()
    try:
        result = jikan_client.fetch_episode_page(mal_id, page=page)
    except JikanNotFoundError:
        repository.mark_complete(mal_id, last_visible_page=page, record_count=len(repository.for_anime(mal_id)))
        return
    repository.upsert(result.get("records", []))
    if result.get("has_next_page"):
        from .maintenance import enqueue_job

        next_page = page + 1
        enqueue_job(
            "jikan_episode_titles",
            {"mal_id": mal_id, "page": next_page},
            idempotency_key=f"jikan-episodes:{mal_id}:{next_page}",
            priority=15,
        )
        return
    repository.mark_complete(
        mal_id,
        last_visible_page=int(result.get("last_visible_page") or page),
        record_count=len(repository.for_anime(mal_id)),
    )


def _enqueue_missing_calendar_airing_windows(
    media_ids: list[str],
    start_utc: datetime,
    end_utc: datetime,
) -> list[str]:
    if not media_ids:
        return []
    from .maintenance import enqueue_job

    repository = _airing_repository()
    pending: list[str] = []
    for utc_month in _utc_month_keys(start_utc, end_utc):
        missing = repository.missing_coverage(media_ids, utc_month)
        if not missing:
            continue
        pending.append(utc_month)
        for offset in range(0, len(missing), 50):
            chunk = missing[offset:offset + 50]
            chunk_key = hashlib.sha1(",".join(chunk).encode("utf-8")).hexdigest()[:12]
            enqueue_job(
                "calendar_airing_window",
                {"media_ids": chunk, "utc_month": utc_month, "page": 1},
                idempotency_key=f"calendar-airing:{utc_month}:{chunk_key}:1",
                priority=20,
            )
    return pending


def _calendar_utc_bounds(
    period_start: date,
    period_end: date,
    settings: dict[str, Any] | None,
) -> tuple[datetime, datetime]:
    display_timezone = _display_timezone(settings)
    start = datetime.combine(period_start, datetime.min.time(), display_timezone)
    end = datetime.combine(period_end + timedelta(days=1), datetime.min.time(), display_timezone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _utc_month_keys(start_utc: datetime, end_utc: datetime) -> list[str]:
    current = start_utc.date().replace(day=1)
    final = (end_utc - timedelta(microseconds=1)).date().replace(day=1)
    months = []
    while current <= final:
        months.append(current.strftime("%Y-%m"))
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)
    return months


def _utc_month_bounds(value: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.strptime(value, "%Y-%m").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise ValueError("Invalid UTC calendar month.") from exc
    next_month = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    return start, next_month

def root_folder_scan_progress() -> dict[str, Any]:
    with _ROOT_SCAN_PROGRESS_LOCK:
        return dict(_ROOT_SCAN_PROGRESS)


def _reset_root_scan_progress(message: str = "") -> None:
    with _ROOT_SCAN_PROGRESS_LOCK:
        _ROOT_SCAN_PROGRESS.clear()
        _ROOT_SCAN_PROGRESS.update(
            {
                "active": True,
                "phase": "Scanning",
                "current": 0,
                "total": 0,
                "percent": 0,
                "message": message,
                "summary": _empty_scan_summary(),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "completed_at": "",
            }
        )


def _update_root_scan_progress(
    *,
    phase: str | None = None,
    current: int | None = None,
    total: int | None = None,
    message: str | None = None,
    summary: dict[str, int] | None = None,
    active: bool | None = None,
) -> None:
    with _ROOT_SCAN_PROGRESS_LOCK:
        if phase is not None:
            _ROOT_SCAN_PROGRESS["phase"] = phase
        if total is not None:
            _ROOT_SCAN_PROGRESS["total"] = max(int(total), 0)
        if current is not None:
            _ROOT_SCAN_PROGRESS["current"] = max(int(current), 0)
        total_value = int(_ROOT_SCAN_PROGRESS.get("total") or 0)
        current_value = int(_ROOT_SCAN_PROGRESS.get("current") or 0)
        _ROOT_SCAN_PROGRESS["percent"] = round((current_value / total_value) * 100) if total_value else 0
        if message is not None:
            _ROOT_SCAN_PROGRESS["message"] = message
        if summary is not None:
            _ROOT_SCAN_PROGRESS["summary"] = dict(summary)
        if active is not None:
            _ROOT_SCAN_PROGRESS["active"] = active
            if not active:
                _ROOT_SCAN_PROGRESS["completed_at"] = datetime.now(timezone.utc).isoformat()


def root_folder_missing() -> bool:
    root_folder = str(user_settings().get("root_folder") or "").strip()
    return not root_folder


def missing_settings_summary(database: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = (
        database.get('settings', {})
        if isinstance(database, dict) and isinstance(database.get('settings'), dict)
        else user_settings()
    )
    missing = []
    if not str(settings.get("root_folder") or "").strip():
        missing.append("root_folder")

    download_client = settings.get("download_client")
    if (
        not isinstance(download_client, dict)
        or not str(download_client.get("implementation") or "").strip()
        or not str(download_client.get("host") or "").strip()
    ):
        missing.append("download_client")

    return {
        "count": len(missing),
        "missing": missing,
    }


def save_root_folder(root_folder: str) -> tuple[bool, str, dict[str, int]]:
    normalized_root = root_folder.strip().strip('"')
    if not normalized_root:
        _update_root_scan_progress(phase="Failed", message="Choose a root folder before saving settings.", active=False)
        message = "Choose a root folder before saving settings."
        _record_standalone_event("settings", message)
        return False, message, _empty_scan_summary()

    path = Path(normalized_root).expanduser()
    _reset_root_scan_progress(f"Validating {path}")
    if not path.exists():
        message = f"Root folder does not exist: {path}"
        _update_root_scan_progress(phase="Failed", message=message, active=False)
        _record_standalone_event("settings", message)
        return False, message, _empty_scan_summary()
    if not path.is_dir():
        message = f"Root folder is not a directory: {path}"
        _update_root_scan_progress(phase="Failed", message=message, active=False)
        _record_standalone_event("settings", message)
        return False, message, _empty_scan_summary()

    resolved_path = path.resolve()
    with _ROOT_SCAN_JOB_LOCK:
        if _root_scan_thread_active():
            message = "A root folder scan is already running. Leave this page if needed; the scan will keep running."
            _update_root_scan_progress(phase="Already scanning", message=message, active=True)
            return False, message, _empty_scan_summary()

        database = _read_user_database()
        database["settings"]["root_folder"] = str(resolved_path)
        _record_event(database, "settings", f"Root folder saved: {resolved_path}. Scan queued in background.")
        _write_user_database(database)
        _reset_root_scan_progress(f"Queued scan for {resolved_path}")
        _start_root_folder_scan_thread(resolved_path)

    return True, f"Root folder saved: {resolved_path}. Scan is running in the background.", _empty_scan_summary()


def _root_scan_thread_active() -> bool:
    if _ROOT_SCAN_THREAD is not None and _ROOT_SCAN_THREAD.is_alive():
        return True
    try:
        from .maintenance import has_active_job

        return has_active_job("root_scan")
    except Exception:
        return False


def _merge_scanned_anime_into_latest(
    latest_library: list[dict[str, Any]],
    scanned_library: list[dict[str, Any]],
    scan_start_ids: set[str],
) -> list[dict[str, Any]]:
    scanned_by_id = {str(anime.get("library_id") or ""): anime for anime in scanned_library if isinstance(anime, dict)}
    removed_scan_ids = scan_start_ids - set(scanned_by_id)
    merged = [
        scanned_by_id.pop(str(anime.get("library_id") or ""), anime)
        for anime in latest_library
        if isinstance(anime, dict) and str(anime.get("library_id") or "") not in removed_scan_ids
    ]
    merged.extend(scanned_by_id.values())
    return merged


def _start_root_folder_scan_thread(root_folder: Path) -> None:
    from .maintenance import enqueue_job

    enqueue_job(
        "root_scan",
        {"root_folder": str(root_folder)},
        idempotency_key=f"root-scan:{str(root_folder).casefold()}",
        priority=95,
    )


def _run_root_folder_scan_job(root_folder: Path) -> None:
    try:
        _update_root_scan_progress(phase="Reading folders", current=0, total=0, message=f"Reading top-level items from {root_folder}")
        children = _root_folder_children(root_folder)
        scan_database = _read_user_database()
        scan_start_ids = {str(anime.get("library_id") or "") for anime in scan_database.get("anime", []) if isinstance(anime, dict)}
        _seed_resolved_metadata_cache_from_library(scan_database["anime"])
        scan_summary = _import_root_folder_children(scan_database, root_folder, children)
        database = _read_user_database()
        database["anime"] = _merge_scanned_anime_into_latest(database.get("anime", []), scan_database.get("anime", []), scan_start_ids)
        database["ignored_torrents"] = scan_database.get("ignored_torrents", database.get("ignored_torrents", []))
        database["unmonitored_titles"] = scan_database.get("unmonitored_titles", database.get("unmonitored_titles", []))
        database["settings"]["root_folder"] = str(root_folder)
        message = f"Root folder scan complete: {root_folder}"
        _record_event(database, "settings", f"{message} Imported={scan_summary['imported']}, updated={scan_summary['updated']}, skipped={scan_summary['skipped']}.")
        _write_user_database(database)
        imported_total = scan_summary["imported"] + scan_summary["updated"] + scan_summary["skipped"]
        _update_root_scan_progress(phase="Complete", current=imported_total, total=imported_total, message=message, summary=scan_summary, active=False)
    except Exception as exc:
        message = f"Root folder scan failed: {exc}"
        _record_standalone_event("settings", message)
        _update_root_scan_progress(phase="Failed", message=message, active=False)


def delete_root_folder() -> tuple[bool, str, dict[str, int]]:
    database = _read_user_database()
    root_folder_imports = [
        anime
        for anime in database["anime"]
        if str(anime.get("library_id") or "").startswith("root-folder:")
    ]
    _seed_resolved_metadata_cache_from_library(root_folder_imports)
    before_count = len(database["anime"])
    database["anime"] = [
        anime
        for anime in database["anime"]
        if not str(anime.get("library_id") or "").startswith("root-folder:")
    ]
    removed_count = before_count - len(database["anime"])
    database["settings"]["root_folder"] = ""
    _record_event(database, "settings", f"Removed root folder and {removed_count} root-folder import(s).")
    _write_user_database(database)
    summary = _empty_scan_summary()
    summary["removed"] = removed_count
    return True, f"Anime root folder removed. {removed_count} root-folder imports removed.", summary


def save_download_client(form: dict[str, Any]) -> tuple[bool, str]:
    client, error = _download_client_from_form(form)
    if error:
        _record_standalone_event("settings", f"Download client save failed: {error}")
        return False, error

    database = _read_user_database()
    database["settings"]["download_client"] = client
    _record_event(database, "settings", f"Saved download client {client['name']} at {client['host']}:{client['port']}.")
    _write_user_database(database)
    return True, "qBittorrent download client saved."


def delete_download_client() -> tuple[bool, str]:
    database = _read_user_database()
    database["settings"]["download_client"] = _empty_download_client_settings()
    _record_event(database, "settings", "Removed download client configuration.")
    _write_user_database(database)
    return True, "Download client configuration removed."


def delete_anime(library_id: str) -> tuple[bool, str]:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return False, "Anime was not found."
    database["anime"] = [
        item
        for item in database.get("anime", [])
        if not (isinstance(item, dict) and str(item.get("library_id") or "") == library_id)
    ]
    _record_event(database, "library", f"Removed {anime.get('title') or anime.get('original_title') or 'anime'} from the library.", anime)
    _write_user_database(database)
    return True, "Anime removed from the library. Local files were not deleted."


def update_anime_preferences(library_id: str, form: dict[str, Any]) -> tuple[bool, str]:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return False, "Anime was not found."
    old_quality = _quality_resolution(anime)
    old_season = _season_hint_value(anime.get("season_number")) or 1
    old_monitored = anime.get("monitored") is not False
    anime["quality_resolution"] = _quality_resolution({"quality_resolution": form.get("quality_resolution")})
    anime["quality_profile"] = _quality_profile_label(anime)
    anime["season_number"] = max(_int_value(form.get("season_number")) or 1, 1)
    anime["monitored"] = form.get("monitored") == "on"
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    cleanup_messages = []
    if not anime["monitored"]:
        _remember_unmonitored_title(database, anime)
        cleanup = _clear_download_plan_for_unmonitored(anime)
        if cleanup["removed_queues"]:
            cleanup_messages.append(f"Cleared {cleanup['removed_queues']} active queued download(s).")
    else:
        _forget_unmonitored_title(database, anime)
        if old_quality != _quality_resolution(anime) or old_season != anime["season_number"]:
            cleanup = _clear_download_plan_for_metadata_override(anime)
            _mark_torrent_search_pending(anime)
            if cleanup["removed_queues"]:
                cleanup_messages.append(f"Cleared {cleanup['removed_queues']} active queued download(s).")
        elif not old_monitored and not _download_need_satisfied(anime):
            _mark_torrent_search_pending(anime)
    cleanup_message = f" {' '.join(cleanup_messages)}" if cleanup_messages else ""
    _record_event(database, "library", f"Updated anime preferences for {anime.get('title', 'anime')}.{cleanup_message}", anime)
    _write_user_database(database)
    return True, "Anime preferences saved." + cleanup_message


def unblock_ignored_torrent(ignore_key: str) -> tuple[bool, str]:
    key = str(ignore_key or "").strip()
    if not key:
        return False, "Blocked torrent key was missing."
    database = _read_user_database()
    ignored = database.get("ignored_torrents")
    if not isinstance(ignored, list):
        return False, "No blocked torrents are stored."
    kept = [item for item in ignored if not (isinstance(item, dict) and str(item.get("key") or "") == key)]
    if len(kept) == len(ignored):
        return False, "Blocked torrent was not found."
    database["ignored_torrents"] = kept
    _record_event(database, "torrent", f"Unblocked torrent candidate {key}.")
    _write_user_database(database)
    return True, "Torrent candidate unblocked. It can be considered by future searches."

def save_display_settings(form: dict[str, Any]) -> tuple[bool, str]:
    selected = _settings_timezone_value(form.get("timezone") if isinstance(form, dict) else None)
    database = _read_user_database()
    database["settings"]["timezone"] = selected
    _record_event(database, "settings", f"Display timezone changed to {selected}.")
    _write_user_database(database)
    return True, f"Display timezone saved as {selected}."


def save_torrent_preferences(form: dict[str, Any]) -> tuple[bool, str]:
    database = _read_user_database()
    settings = database.setdefault("settings", {})
    if not isinstance(settings, dict):
        settings = _empty_user_database()["settings"]
        database["settings"] = settings
    settings["preferred_subbers"] = _normalized_preferred_subbers(form.get("preferred_subbers") if isinstance(form, dict) else None)
    threshold = _posted_confidence_threshold(form.get("torrent_confidence_threshold") if isinstance(form, dict) else None)
    if threshold is None:
        return False, "Enter a confidence threshold between 1 and 100."
    settings["torrent_confidence_threshold"] = threshold
    _record_event(
        database,
        "settings",
        f"Torrent preferences saved: preferred subbers={', '.join(settings['preferred_subbers'])}; confidence threshold={threshold}.",
    )
    _write_user_database(database)
    return True, "Torrent preferences saved."

def test_download_client(form: dict[str, Any] | None = None) -> tuple[bool, str]:
    if form is not None and form.get("implementation"):
        client, error = _download_client_from_form(form)
        if error:
            _record_standalone_event("settings", f"Download client test failed: {error}")
            return False, error
        client["enabled"] = True
    else:
        client = user_settings().get("download_client")
    if not isinstance(client, dict) or not client.get("implementation"):
        message = "No download client is configured."
        _record_standalone_event("settings", f"Download client test failed: {message}")
        return False, message
    if client.get("implementation") != "qbittorrent":
        message = "Nyaarr currently only supports qBittorrent."
        _record_standalone_event("settings", f"Download client test failed: {message}")
        return False, message
    if not client.get("enabled"):
        message = "The configured qBittorrent client is disabled."
        _record_standalone_event("settings", f"Download client test failed: {message}")
        return False, message

    try:
        qbittorrent = client_from_settings({"download_client": client}, timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS)
        version = qbittorrent.version()
    except QBittorrentError as exc:
        message = f"qBittorrent connection failed: {exc}."
        _record_standalone_event("settings", f"Download client test failed: {message}")
        return False, message

    message = f"Connected to qBittorrent {version or 'Web API'}."
    _record_standalone_event("settings", f"Download client test succeeded: {message}")
    return True, message


def allow_flagged_torrent(library_id: str) -> tuple[bool, str]:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return False, "Anime was not found."
    queue = anime.get("download_queue")
    if not isinstance(queue, dict) or queue.get("status") != "flagged":
        return False, "No flagged torrent is waiting for this anime."

    queue["safety_status"] = "allowed"
    queue["status"] = "queued"
    queue["message"] = "User allowed flagged torrent."
    try:
        client = client_from_settings(database["settings"], timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS)
        if not queue.get("user_add_paused"):
            client.resume(str(queue.get("hash") or ""))
            queue["message"] = "User allowed flagged torrent and qBittorrent was resumed."
    except QBittorrentError as exc:
        queue["message"] = f"User allowed flagged torrent, but qBittorrent resume failed: {exc}"
    _record_event(database, "torrent", queue["message"], anime, queue)
    _write_user_database(database)
    return True, queue["message"]


def reject_flagged_torrent(library_id: str) -> tuple[bool, str]:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return False, "Anime was not found."
    queue = anime.get("download_queue")
    if not isinstance(queue, dict) or queue.get("status") != "flagged":
        return False, "No flagged torrent is waiting for this anime."

    _record_ignored_torrent(database, anime, queue)
    try:
        client = client_from_settings(database["settings"], timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS)
        torrent_hash = str(queue.get("hash") or "")
        if torrent_hash:
            client.delete(torrent_hash, delete_files=False)
    except QBittorrentError as exc:
        _append_torrent_notice(anime, f"Rejected flagged torrent, but qBittorrent delete failed: {exc}")

    rejected_queue = {
        "status": "rejected",
        "client": "qBittorrent",
        "title": queue.get("title", ""),
        "detail_url": queue.get("detail_url", ""),
        "rejected_at": datetime.now(timezone.utc).isoformat(),
        "message": "Rejected flagged torrent and added it to the ignore list.",
    }
    rejected_identity = _queue_identity(queue)
    replaced = False
    updated_queues = []
    for existing_queue in _download_queue_items(anime):
        if not replaced and _queue_identity(existing_queue) == rejected_identity:
            updated_queues.append(rejected_queue)
            replaced = True
        else:
            updated_queues.append(existing_queue)
    if not replaced:
        updated_queues.append(rejected_queue)
    anime["download_queues"] = updated_queues
    anime["download_queue"] = rejected_queue
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    _refresh_torrent_search(anime)
    _maybe_dispatch_torrent(database, anime)
    _record_event(database, "torrent", "Rejected flagged torrent and added it to the ignore list.", anime, rejected_queue)
    _write_user_database(database)
    return True, "Rejected flagged torrent and added it to the ignore list."


def add_anime_to_library(anime: dict[str, Any], torrent_search: dict[str, Any], supplied_torrent_link: str = "") -> dict[str, Any]:
    database = _read_user_database()
    library = database["anime"]
    existing = next((item for item in library if item["library_id"] == anime["library_id"]), None)

    library_item = {
        **anime,
        "monitored": existing.get("monitored", True) if existing is not None else True,
        "library_state": "Monitored",
        "quality_resolution": _quality_resolution(anime),
        "quality_profile": _quality_profile_label(anime),
        "torrent_search": torrent_search,
    }
    _attach_existing_root_episode_files(database, library_item)
    _refresh_library_state(library_item, root_folder_configured=_root_folder_configured(database))
    _mark_anilist_reconciliation_for_current_metadata(library_item)
    _refresh_airing_state(library_item)
    supplied_release, supplied_error = _supplied_add_torrent_release(library_item, supplied_torrent_link, database)
    if supplied_error:
        _append_torrent_notice(library_item, supplied_error)
    if library_item.get("monitored") is False:
        _clear_download_plan_for_unmonitored(library_item)
    elif supplied_release:
        _queue_supplied_add_torrent(library_item, supplied_release)
    else:
        _queue_background_torrent_search(library_item)
    if existing is not None:
        existing.update(library_item)
        _sync_anime_nfo_file(existing)
        _record_event(database, "library", f"Updated anime library entry for {library_item.get('title', 'anime')}.", existing)
        _write_user_database(database)
        return existing

    library.append(library_item)
    _sync_anime_nfo_file(library_item)
    _record_event(database, "library", f"Added {library_item.get('title', 'anime')} to the library.", library_item)
    _write_user_database(database)
    return library_item


def _supplied_add_torrent_release(
    anime: dict[str, Any],
    torrent_link: str,
    database: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    link = str(torrent_link or "").strip()
    if not link:
        return {}, ""
    release, error = _manual_torrent_release(anime, link)
    if error:
        return {}, error
    score, reasons = _torrent_candidate_confidence(release, database, anime)
    release["confidence"] = max(score, _torrent_confidence_threshold(database))
    release["confidence_reasons"] = reasons + ["provided while adding anime"]
    release["autofill_from_torrent_files"] = True
    release["release_kind"] = "batch"
    release["episode"] = None
    return release, ""


def _queue_background_torrent_search(anime: dict[str, Any]) -> None:
    if anime.get("monitored") is False:
        _clear_download_plan_for_unmonitored(anime)
        return
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "Queued for background torrent search",
        "candidates": [],
        "notices": ["Torrent search will run in the background after this anime is added."],
    }


def _queue_supplied_add_torrent(anime: dict[str, Any], release: dict[str, Any]) -> None:
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "User supplied Nyaa torrent link queued for background dispatch",
        "candidates": [release],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "notices": [
            "Supplied Nyaa link was queued first; the background worker will send it to qBittorrent.",
            "Torrent search will run later for any remaining missing episodes.",
        ],
    }


def assign_manual_torrent_url(library_id: str, torrent_link: str, episode: str = "") -> tuple[bool, str]:
    database = _read_user_database()
    anime = next((item for item in database.get("anime", []) if str(item.get("library_id") or "") == library_id), None)
    if not isinstance(anime, dict):
        return False, "Anime was not found in the library."
    release, error = _manual_torrent_release(anime, torrent_link, episode)
    if error:
        return False, error
    score, reasons = _torrent_candidate_confidence(release, database, anime)
    release["confidence"] = max(score, _torrent_confidence_threshold(database))
    release["confidence_reasons"] = reasons + ["provided manually"]
    _set_release_group_lock_from_release(anime, release, "manual")
    torrent_search = anime.setdefault("torrent_search", {})
    candidates = torrent_search.setdefault("candidates", [])
    if isinstance(candidates, list) and all(_torrent_ignore_key(candidate) != _torrent_ignore_key(release) for candidate in candidates if isinstance(candidate, dict)):
        candidates.insert(0, release)
    _maybe_dispatch_torrent(database, anime, forced_release=release)
    _refresh_manual_dispatch_queue(database, anime, release)
    _search_and_dispatch_locked_group(database, anime)
    _reopen_manual_selection_for_remaining_candidates(database, anime)
    _record_event(database, "torrent", f"User submitted manual torrent link for {anime.get('title', 'anime')}.", anime, release)
    _write_user_database(database)
    if any(queue.get("torrent_url") == release.get("torrent_url") for queue in _download_queue_items(anime)):
        return True, "Manual torrent link was sent to qBittorrent."
    updated_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    notices = updated_search.get("notices") if isinstance(updated_search.get("notices"), list) else []
    return False, str(notices[-1]) if notices else "Manual torrent link could not be queued."

def assign_manual_torrent(library_id: str, selection_key: str) -> tuple[bool, str]:
    database = _read_user_database()
    anime = next((item for item in database.get("anime", []) if str(item.get("library_id") or "") == library_id), None)
    if not isinstance(anime, dict):
        return False, "Anime was not found in the library."
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    selected = next((candidate for candidate in candidates if isinstance(candidate, dict) and _torrent_ignore_key(candidate) == selection_key), None)
    if not isinstance(selected, dict):
        return False, "Selected torrent candidate was not found."
    release = dict(selected)
    score, reasons = _torrent_candidate_confidence(release, database, anime)
    release["confidence"] = score
    release["confidence_reasons"] = reasons + ["selected manually"]
    _maybe_dispatch_torrent(database, anime, forced_release=release)
    _refresh_manual_dispatch_queue(database, anime, release)
    _reopen_manual_selection_for_remaining_candidates(database, anime)
    _record_event(database, "torrent", f"User selected manual torrent {release.get('title', 'selected torrent')}.", anime, release)
    _write_user_database(database)
    if any(queue.get("torrent_url") == release.get("torrent_url") for queue in _download_queue_items(anime)):
        return True, "Selected torrent was sent to qBittorrent."
    updated_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    notices = updated_search.get("notices") if isinstance(updated_search.get("notices"), list) else []
    return False, str(notices[-1]) if notices else "Selected torrent could not be queued."


def _refresh_manual_dispatch_queue(database: dict[str, Any], anime: dict[str, Any], release: dict[str, Any]) -> None:
    client_settings = database.get("settings", {}).get("download_client")
    if not isinstance(client_settings, dict) or client_settings.get("implementation") != "qbittorrent" or not client_settings.get("enabled"):
        return
    release_url = str(release.get("torrent_url") or "")
    if not release_url:
        return
    if not any(queue.get("torrent_url") == release_url for queue in _download_queue_items(anime)):
        return
    _refresh_download_queue(database)


def _search_and_dispatch_locked_group(database: dict[str, Any], anime: dict[str, Any]) -> None:
    locked_group = _locked_release_group(anime)
    if not locked_group or not _missing_episode_numbers(anime):
        return
    _refresh_torrent_search(anime, database)
    _maybe_dispatch_torrent(database, anime)
    _append_torrent_notice(anime, f"Searched remaining missing episodes using locked release group {locked_group}.")


def reject_manual_torrent(library_id: str, selection_key: str) -> tuple[bool, str]:
    database = _read_user_database()
    anime = next((item for item in database.get("anime", []) if str(item.get("library_id") or "") == library_id), None)
    if not isinstance(anime, dict):
        return False, "Anime was not found in the library."
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    selected = next((candidate for candidate in candidates if isinstance(candidate, dict) and _torrent_ignore_key(candidate) == selection_key), None)
    if not isinstance(selected, dict):
        return False, "Selected torrent candidate was not found."

    _record_ignored_torrent(database, anime, selected)
    anime["torrent_manual_selection"] = {"required": False}
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    _refresh_torrent_search(anime, database)
    _maybe_dispatch_torrent(database, anime)
    _record_event(database, "torrent", f"User rejected manual torrent {selected.get('title', 'selected torrent')}.", anime, selected)
    _write_user_database(database)

    if _active_download_queue(anime):
        return True, "Rejected candidate and queued the next suitable torrent."
    if _manual_selection_required(anime):
        return True, "Rejected candidate and refreshed manual selection with remaining candidates."
    return True, "Rejected candidate and refreshed torrent search."


def find_library_anime(library_id: str) -> dict[str, Any] | None:
    return next((anime for anime in anime_library() if anime["library_id"] == library_id), None)


def library_stats(library: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    library = library if library is not None else anime_library()
    completed_count = sum(1 for anime in library if anime.get("library_state") == "Completed")
    airing_count = sum(1 for anime in library if _is_currently_airing(anime))
    not_yet_aired_count = sum(1 for anime in library if _airing_state(anime) == "Not Yet Aired")
    return [
        {"label": "Total Anime", "value": str(len(library)), "tone": "dark-blue"},
        {"label": "Completed", "value": str(completed_count), "tone": "green"},
        {"label": "Airing", "value": str(airing_count), "tone": "blue"},
        {"label": "Not Yet Aired", "value": str(not_yet_aired_count), "tone": "yellow"},
    ]


def sidebar_counts(database: dict[str, Any] | None = None) -> dict[str, int]:
    database = database if database is not None else _read_user_database()
    library = database["anime"]
    wanted_count = sum(
        1
        for anime in library
        if not anime.get("torrent_search", {}).get("candidates", [])
    )
    manual_items, manual_changed = _manual_selection_items(database)
    if manual_changed:
        _write_user_database(database)
    return {
        "anime": len(library),
        "activity": _queued_activity_count(library),
        "manual_selection": len(manual_items),
        "metadata_verification": _metadata_verification_count(library),
        "wanted": wanted_count,
        "settings_missing": missing_settings_summary(database)["count"],
        "events": _event_count(database),
    }


def activity_model(section: str) -> dict[str, Any]:
    database = _read_user_database()
    selected = section if section in {"queued", "history", "blocked"} else "queued"
    rows = {
        "queued": _activity_queued_rows(database),
        "history": _activity_history_rows(database),
        "blocked": _activity_blocked_rows(database),
    }
    labels = {"queued": "Queued", "history": "History", "blocked": "Blocked"}
    descriptions = {
        "queued": "Incomplete Nyaarr torrents currently queued, checking, or downloading.",
        "history": "Nyaarr torrents that reached completion or were imported.",
        "blocked": "Rejected flagged torrents kept out of future candidate selection.",
    }
    selected_rows = rows[selected]
    page_size = 200
    return {
        "section": selected,
        "label": labels[selected],
        "description": descriptions[selected],
        "rows": selected_rows[:page_size],
        "total_rows": len(selected_rows),
        "has_more": len(selected_rows) > page_size,
        "counts": {key: len(value) for key, value in rows.items()},
    }


def hard_reset_queued_torrents(selections: list[str] | None = None) -> tuple[bool, str]:
    database = _read_user_database()
    selected_rows: dict[str, set[str]] = {}
    for selection in selections or []:
        library_id, separator, episode_label = str(selection).partition("|")
        if separator and library_id and episode_label:
            selected_rows.setdefault(library_id, set()).add(episode_label)
    selected_mode = selections is not None
    if selected_mode and not selected_rows:
        return False, "Select at least one queued episode to reset."
    snapshot = _download_client_existing_snapshot(database)
    client_keys = snapshot.get("keys") if isinstance(snapshot.get("keys"), set) else set()
    episodes_by_library_id = snapshot.get("episodes_by_library_id") if isinstance(snapshot.get("episodes_by_library_id"), dict) else {}
    reset_anime = 0
    cleared_queues = 0

    for anime in database.get("anime", []):
        if not isinstance(anime, dict) or anime.get("monitored") is False or not _missing_episode_numbers(anime):
            continue
        library_id = str(anime.get("library_id") or "")
        if selected_mode and library_id not in selected_rows:
            continue
        selected_episode_labels = selected_rows.get(library_id, set())
        client_episodes = episodes_by_library_id.get(library_id, set())
        retained = []
        removed = []
        for queue in _download_queue_items(anime):
            status = str(queue.get("status") or "")
            episode = _int_value(queue.get("episode"))
            visible = _queue_identity(queue) in client_keys or (episode is not None and episode in client_episodes)
            selected_queue = not selected_mode or _activity_episode_label(queue) in selected_episode_labels
            if not selected_queue or status in {"completed", "imported", "rejected", "superseded"} or visible:
                retained.append(queue)
            else:
                removed.append(queue)
        if removed:
            _archive_download_queues(anime, removed)
            cleared_queues += len(removed)
        anime["download_queues"] = retained
        _sync_primary_download_queue(anime, retained)
        anime["torrent_search"] = {
            "query": str(anime.get("title") or anime.get("original_title") or ""),
            "strategy": "Hard reset queued for fresh torrent discovery",
            "candidates": [],
            "checked_at": "",
            "notices": ["Queued state was hard-reset; fresh alias and release-group searches are pending."],
        }
        anime["torrent_manual_selection"] = {"required": False}
        anime.pop("torrent_dispatch_attempted_at", None)
        anime.pop("torrent_dispatch_backlog", None)
        reset_anime += 1

    if not reset_anime:
        return False, "No monitored anime with pending episodes needed a reset."

    scope_label = "selected queued rows" if selected_mode else "queued torrent state"
    message = f"Hard-reset {scope_label} for {reset_anime} anime; cleared {cleared_queues} stale queue record(s)."
    _record_event(database, "torrent", message)
    _write_user_database(database)
    from .maintenance import enqueue_job

    enqueue_job(
        "external_refresh",
        idempotency_key=f"queued-hard-reset:{time.time_ns()}",
        priority=100,
    )
    return True, message + " Fresh discovery and bounded dispatch were prioritized in the background."


def anime_detail_model(library_id: str) -> dict[str, Any] | None:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return None
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    episode_titles, episode_titles_pending = _episode_title_state(anime)
    return {
        "library_id": str(anime.get("library_id") or ""),
        "title": str(anime.get("title") or anime.get("original_title") or "Unknown"),
        "original_title": str(anime.get("original_title") or ""),
        "poster": str(anime.get("poster") or anime.get("poster_url") or ""),
        "synopsis": str(anime.get("synopsis") or ""),
        "year": str(anime.get("year") or "Unknown"),
        "status": str(anime.get("status") or "Unknown"),
        "library_state": str(anime.get("library_state") or "Unknown"),
        "airing_state": str(anime.get("airing_state") or "Unknown"),
        "air_date": _anime_detail_date(anime.get("start_date") or anime.get("air_date")),
        "runtime": str(anime.get("runtime") or "Unknown"),
        "studio": str(anime.get("studio") or "Unknown"),
        "source": str(anime.get("source") or "Unknown"),
        "rating": str(anime.get("rating") or "Unrated"),
        "genres": anime.get("genres") if isinstance(anime.get("genres"), list) else [],
        "media_format": str(anime.get("media_format") or "Unknown"),
        "release_season": str(anime.get("release_season") or ""),
        "season_year": str(anime.get("season_year") or ""),
        "source_material": str(anime.get("source_material") or ""),
        "quality_profile": str(anime.get("quality_profile") or _quality_profile_label(anime)),
        "quality_resolution": _quality_resolution(anime),
        "season_number": _season_hint_value(anime.get("season_number")) or 1,
        "monitored": anime.get("monitored") is not False,
        "completion": anime.get("completion") if isinstance(anime.get("completion"), dict) else {},
        "local_path": str(anime.get("local_path") or ""),
        "torrent_strategy": str((anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}).get("strategy") or ""),
        "provider_ids": anime.get("provider_ids") if isinstance(anime.get("provider_ids"), dict) else {},
        "anilist_id": _provider_id_value(anime, "anilist"),
        "manual_anilist_id": str(anime.get("manual_anilist_id") or ""),
        "episodes": _anime_episode_rows(anime, episode_titles),
        "episode_titles_pending": episode_titles_pending,
    }


def anime_episode_titles_model(library_id: str) -> dict[str, Any] | None:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return None
    records, pending = _episode_title_state(anime)
    return {
        "titles": {
            str(episode): _episode_title_text(record, episode)
            for episode, record in records.items()
            if _episode_title_text(record, episode) != f"Episode {episode}"
        },
        "pending": pending,
        "source": "Jikan",
    }


def _episode_title_state(anime: dict[str, Any]) -> tuple[dict[int, dict[str, Any]], bool]:
    mal_id = _provider_id_value(anime, "mal")
    if not mal_id:
        return {}, False
    repository = _episode_title_repository()
    records = {
        int(record["episode"]): record
        for record in repository.for_anime(mal_id)
        if _int_value(record.get("episode")) is not None
    }
    pending = _ensure_jikan_episode_titles(anime)
    return records, pending


def _ensure_jikan_episode_titles(anime: dict[str, Any]) -> bool:
    mal_id = _provider_id_value(anime, "mal")
    if not mal_id or not mal_id.isdigit() or int(mal_id) <= 0:
        return False
    repository = _episode_title_repository()
    max_age = (
        JIKAN_FINISHED_TITLE_REFRESH_MAX_AGE_SECONDS
        if _is_finished_status(anime.get("status"))
        else JIKAN_ONGOING_TITLE_REFRESH_MAX_AGE_SECONDS
    )
    if not repository.is_due(mal_id, max_age_seconds=max_age):
        return repository.is_pending(mal_id)
    try:
        from .maintenance import enqueue_job

        enqueue_job(
            "jikan_episode_titles",
            {"mal_id": mal_id, "page": 1},
            idempotency_key=f"jikan-episodes:{mal_id}:1",
            priority=15,
        )
        repository.mark_requested(mal_id)
    except Exception:
        return repository.is_pending(mal_id)
    return True


def _anime_episode_rows(
    anime: dict[str, Any],
    episode_titles: dict[int, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    completion = anime.get("completion") if isinstance(anime.get("completion"), dict) else {}
    expected = _int_value(completion.get("expected_episodes")) or _expected_episode_count(anime)
    progress_target = _int_value(completion.get("progress_target")) or expected
    local_files = _local_episode_file_map(anime)
    queue_map = _episode_queue_map(anime)
    media_id = _provider_id_value(anime, "anilist")
    schedule_by_episode = {
        int(record["episode"]): record
        for record in (_airing_repository().for_media(media_id) if media_id else [])
    }
    total = max([value for value in [expected, progress_target, *local_files.keys(), *queue_map.keys()] if isinstance(value, int)] or [0])
    if total <= 0:
        return []

    season = _selected_season_number_for_detail(anime)
    rows = []
    for episode in range(1, total + 1):
        queue = queue_map.get(episode)
        file_path = local_files.get(episode, "")
        if file_path:
            state = "Downloaded"
            tone = "downloaded"
        elif queue is not None:
            state = _episode_queue_state(queue)
            tone = "queued"
        elif progress_target is not None and episode > progress_target:
            state = "Unaired"
            tone = "unaired"
        else:
            state = "Missing"
            tone = "missing"
        rows.append(
            {
                "season": season,
                "episode": episode,
                "label": f"S{season:02d}E{episode:02d}",
                "title": _episode_title_text((episode_titles or {}).get(episode), episode),
                "air_date": _episode_air_date_label(anime, episode, schedule_by_episode),
                "air_date_precision": str(schedule_by_episode.get(episode, {}).get("precision") or ""),
                "status": state,
                "tone": tone,
                "file": Path(file_path).name if file_path else "",
                "path": file_path,
                "quality": _episode_quality_label(anime, queue),
                "progress": _activity_progress(queue) if queue is not None else None,
            }
        )
    return rows


def _episode_title_text(record: dict[str, Any] | None, episode: int) -> str:
    if isinstance(record, dict):
        for field in ("title", "title_romanji", "title_japanese"):
            value = str(record.get(field) or "").strip()
            if value:
                return value
    return f"Episode {episode}"


def _local_episode_file_map(anime: dict[str, Any]) -> dict[int, str]:
    files = anime.get("episode_files")
    if not isinstance(files, list):
        return {}
    paths = _episode_file_paths_for_selected_season(anime, files)
    if len(paths) == 1 and _expected_episode_count(anime) == 1:
        return {1: paths[0]}

    mapped: dict[int, str] = {}
    for path in paths:
        episode = episode_number_from_title(Path(path).name)
        if episode is not None and episode > 0:
            mapped[episode] = path
    return mapped


def _episode_queue_map(anime: dict[str, Any]) -> dict[int, dict[str, Any]]:
    mapped: dict[int, dict[str, Any]] = {}
    for queue in _download_queue_items(anime):
        if queue.get("status") not in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged", "completed", "imported"}:
            continue
        episode = _int_value(queue.get("episode"))
        if episode is not None and episode > 0:
            mapped[episode] = queue
            continue
        wanted = queue.get("wanted_episodes")
        if isinstance(wanted, list):
            for value in wanted:
                wanted_episode = _int_value(value)
                if wanted_episode is not None and wanted_episode > 0:
                    mapped.setdefault(wanted_episode, queue)
    return mapped


def _episode_queue_state(queue: dict[str, Any]) -> str:
    status = str(queue.get("status") or "queued").replace("_", " ").title()
    if status == "Pending Safety":
        return "Checking"
    return status


def _episode_quality_label(anime: dict[str, Any], queue: dict[str, Any] | None) -> str:
    if queue is not None:
        label = _activity_resolution_label(anime, queue)
        if label and label != "Unknown":
            return label
    for value in (anime.get("quality_tag"), anime.get("quality_resolution"), anime.get("quality_profile")):
        label = str(value or "").strip()
        if label:
            return label
    return "Unknown"


def _episode_air_date_label(
    anime: dict[str, Any],
    episode: int,
    schedule_by_episode: dict[int, dict[str, Any]] | None = None,
) -> str:
    record = (schedule_by_episode or {}).get(episode)
    if record and record.get("airing_at"):
        label = _display_datetime_label(record.get("airing_at"))
        return f"{label} (estimated)" if record.get("precision") == "estimated" else label
    airing_episode = _int_value(anime.get("airing_episode"))
    if airing_episode == episode and anime.get("next_airing_at"):
        return _display_datetime_label(anime.get("next_airing_at"))
    return "TBA"


def _anime_detail_date(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return value.strip()
    return _display_date_label(parsed)


def _selected_season_number_for_detail(anime: dict[str, Any]) -> int:
    return max(_int_value(anime.get("season_number")) or 1, 1)

def _active_activity_count(library: list[dict[str, Any]]) -> int:
    return _queued_activity_count(library)


def _queued_activity_count(library: list[dict[str, Any]]) -> int:
    return len(_activity_queued_rows({"anime": library}))


def manual_selection_model() -> dict[str, Any]:
    database = _read_user_database()
    items, changed = _manual_selection_items(database)
    if changed:
        _write_user_database(database)
    return {"items": items, "count": len(items)}


def _manual_selection_items(database: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    client_snapshot = _download_client_existing_snapshot(database)
    items: list[dict[str, Any]] = []
    changed = False
    for anime in database.get("anime", []):
        if not isinstance(anime, dict):
            continue
        manual = anime.get("torrent_manual_selection")
        if not isinstance(manual, dict) or not manual.get("required"):
            continue
        torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
        candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
        rows = _visible_manual_candidates(database, anime, client_snapshot)
        if not rows and candidates:
            _clear_stale_manual_candidates(anime)
            changed = True
            continue
        if not rows and not candidates and str(manual.get("intervention_type") or "") != "no_candidates":
            anime["torrent_manual_selection"] = {"required": False}
            changed = True
            continue
        items.append(
            {
                "library_id": str(anime.get("library_id") or ""),
                "title": str(anime.get("title") or anime.get("original_title") or "Unknown"),
                "poster_url": str(anime.get("poster") or anime.get("poster_url") or ""),
                "reason": str(manual.get("reason") or "Candidate confidence is too low."),
                "confidence": int(manual.get("confidence") or 0),
                "best_candidate_title": str(manual.get("best_candidate_title") or ""),
                "candidates": [_manual_candidate_row(candidate) for candidate in rows[:8]],
                "needed_episodes": _manual_needed_episode_rows(anime),
                "can_submit_url": True,
            }
        )
    return items, changed


def _manual_needed_episode_rows(anime: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "episode": episode,
            "label": f"Episode {episode}",
            "resolution": _activity_resolution_label(anime, {}),
        }
        for episode in _missing_episode_numbers(anime)
    ]


def _visible_manual_candidates(
    database: dict[str, Any],
    anime: dict[str, Any],
    client_snapshot: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    if not candidates:
        return []

    snapshot = client_snapshot if client_snapshot is not None else _download_client_existing_snapshot(database)
    ignored_keys = _ignored_torrent_keys(database)
    queued_keys = _active_queue_identity_keys(anime)
    queued_episodes = _queued_episode_numbers(anime)
    queued_episodes.update(_download_client_queued_episodes(anime, snapshot))
    missing_episodes = _missing_episode_numbers(anime)
    allows_bluray = _quality_resolution(anime) == "BD"
    rows: list[dict[str, Any]] = []

    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("source_kind") == "bluray" and not allows_bluray:
            continue
        if _torrent_ignore_key(candidate) in ignored_keys:
            continue
        if _queue_identity(candidate) in queued_keys:
            continue
        if _candidate_already_in_download_client(candidate, anime, snapshot):
            continue
        candidate_episode = _int_value(candidate.get("episode"))
        if missing_episodes and candidate.get("release_kind") == "episode":
            if candidate_episode not in missing_episodes or candidate_episode in queued_episodes:
                continue
        scored_candidate = dict(candidate)
        score, reasons = _torrent_candidate_confidence(scored_candidate, database, anime)
        scored_candidate["confidence"] = score
        scored_candidate["confidence_reasons"] = reasons
        rows.append(scored_candidate)

    return sorted(rows, key=lambda item: _candidate_selection_sort_key(item, database, anime), reverse=True)


def _clear_stale_manual_candidates(anime: dict[str, Any]) -> None:
    anime["torrent_manual_selection"] = {"required": False}
    torrent_search = anime.setdefault("torrent_search", {})
    if isinstance(torrent_search, dict):
        torrent_search["candidates"] = []
        torrent_search["checked_at"] = ""
        torrent_search["strategy"] = "Queued for background torrent search"
    _append_torrent_notice(
        anime,
        "Manual selection was cleared because all stored candidates are already present in qBittorrent or no longer selectable. A fresh torrent search will run.",
    )


def _reopen_manual_selection_for_remaining_candidates(database: dict[str, Any], anime: dict[str, Any]) -> None:
    rows = _visible_manual_candidates(database, anime)
    if not rows:
        return
    best = rows[0]
    threshold = _torrent_confidence_threshold(database)
    confidence = int(best.get("confidence") or 0)
    reason = f"Best remaining torrent confidence is below {threshold}." if confidence < threshold else "Remaining torrent candidates need manual confirmation."
    _set_manual_selection_required(anime, confidence, reason, str(best.get("title") or ""))


def _manual_selection_count(library: list[dict[str, Any]]) -> int:
    return sum(1 for anime in library if _manual_selection_required(anime))


def _metadata_verification_count(library: list[dict[str, Any]]) -> int:
    return sum(1 for anime in library if anime.get("manual_verification_required"))

def event_log_model(limit: int = 100) -> dict[str, Any]:
    database = _read_user_database()
    rows = event_log_rows(limit=limit, database=database)
    return {"rows": rows, "count": _event_count(database)}


def event_log_rows(limit: int | None = 100, database: dict[str, Any] | None = None) -> list[dict[str, str]]:
    database = database if database is not None else _read_user_database()
    events = database.get("events") if isinstance(database.get("events"), list) else []
    rows = [_event_row(event) for event in events if isinstance(event, dict)]
    rows.sort(key=lambda row: row["sort_date"], reverse=True)
    return rows if limit is None else rows[:limit]


def _record_standalone_event(category: str, message: str, anime: dict[str, Any] | None = None, torrent: dict[str, Any] | None = None) -> None:
    database = _read_user_database()
    _record_event(database, category, message, anime, torrent)
    _write_user_database(database)


def _event_count(database: dict[str, Any]) -> int:
    events = database.get("events")
    return len(events) if isinstance(events, list) else 0


def _record_event(database: dict[str, Any], category: str, message: str, anime: dict[str, Any] | None = None, torrent: dict[str, Any] | None = None) -> None:
    events = database.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        database["events"] = events
    events.append(
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "category": category,
            "message": message,
            "anime_library_id": str((anime or {}).get("library_id") or ""),
            "anime_title": str((anime or {}).get("title") or (anime or {}).get("original_title") or ""),
            "torrent_title": str((torrent or {}).get("title") or ""),
            "status": str((torrent or {}).get("status") or ""),
        }
    )
    del events[:-200]


def _event_row(event: dict[str, Any]) -> dict[str, str]:
    return {
        "created_at": _display_datetime_label(event.get("created_at")),
        "sort_date": str(event.get("created_at") or ""),
        "category": str(event.get("category") or "Event"),
        "message": str(event.get("message") or ""),
        "anime": str(event.get("anime_title") or ""),
        "torrent": str(event.get("torrent_title") or ""),
        "status": str(event.get("status") or ""),
    }

def metadata_verification_model() -> dict[str, Any]:
    database = _read_user_database()
    items = []
    for anime in database.get("anime", []):
        if not isinstance(anime, dict) or not anime.get("manual_verification_required"):
            continue
        candidates = _metadata_review_candidates(anime)
        items.append(
            {
                "library_id": str(anime.get("library_id") or ""),
                "title": str(anime.get("title") or anime.get("original_title") or "Unknown"),
                "local_path": str(anime.get("local_path") or ""),
                "reason": str(anime.get("manual_verification_reason") or "Metadata needs user verification."),
                "poster_url": str(anime.get("poster") or ""),
                "episode_files": len(anime.get("episode_files") if isinstance(anime.get("episode_files"), list) else []),
                "candidates": [_metadata_candidate_row(candidate) for candidate in candidates if isinstance(candidate, dict)],
            }
        )
    return {"items": items, "count": len(items)}


def apply_manual_anilist_id(library_id: str, anilist_id: str) -> tuple[bool, str]:
    selected_id = str(anilist_id or "").strip()
    if not re.fullmatch(r"\d+", selected_id):
        return False, "Enter a valid numeric AniList ID."

    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return False, "Anime was not found."

    try:
        metadata = search_anilist_by_id(selected_id)
    except MetadataProviderError as exc:
        return False, f"AniList lookup failed: {exc}"
    if not isinstance(metadata, dict):
        return False, f"AniList anime {selected_id} was not found."

    anime.setdefault("torrent_search", {"candidates": [], "notices": []})
    if not isinstance(anime.get("torrent_search"), dict):
        anime["torrent_search"] = {"candidates": [], "notices": []}
    search_titles = [str(anime.get("title") or anime.get("original_title") or metadata.get("title") or "Anime")]
    _apply_resolved_metadata(anime, metadata, search_titles, "manual-anilist-id")
    anime["provider_ids"]["anilist"] = selected_id
    anime["manual_anilist_id"] = selected_id
    anime["anilist_metadata_checked_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    anime.pop("anilist_metadata_error", None)
    _mark_anilist_reconciliation_resolved(anime)
    cleanup = _clear_download_plan_for_metadata_override(anime)
    _refresh_media_tag(anime)
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    _sync_anime_nfo_file(anime)
    _mark_torrent_search_pending(anime)
    message = f"Updated {anime.get('title', 'anime')} from AniList ID {selected_id}. Cleared {cleanup['removed_queues']} queued download(s)."
    _record_event(database, "metadata", message, anime)
    _write_user_database(database)
    return True, message

def _clear_download_plan_for_metadata_override(anime: dict[str, Any]) -> dict[str, int]:
    queues = _download_queue_items(anime)
    kept = [queue for queue in queues if queue.get("status") in {"completed", "imported"}]
    removed = len(queues) - len(kept)
    anime["download_queues"] = kept
    _sync_primary_download_queue(anime, kept)
    anime["torrent_manual_selection"] = {"required": False}
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "Queued for background torrent search",
        "candidates": [],
        "notices": ["Metadata was manually changed; previous torrent candidates and queued episode downloads were cleared."],
    }
    return {"removed_queues": removed, "kept_history": len(kept)}

def _clear_download_plan_for_unmonitored(anime: dict[str, Any]) -> dict[str, int]:
    queues = _download_queue_items(anime)
    kept = [queue for queue in queues if queue.get("status") in {"completed", "imported"}]
    removed = len(queues) - len(kept)
    anime["download_queues"] = kept
    _sync_primary_download_queue(anime, kept)
    anime["torrent_manual_selection"] = {"required": False}
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "Torrent search paused because anime is unmonitored",
        "candidates": [],
        "notices": ["Anime is unmonitored; queued torrent downloads and candidates were cleared."],
    }
    return {"removed_queues": removed, "kept_history": len(kept)}


def apply_metadata_verification(library_id: str, selection_key: str) -> tuple[bool, str]:
    database = _read_user_database()
    anime = _find_database_anime(database, library_id)
    if anime is None:
        return False, "Anime was not found."
    if not anime.get("manual_verification_required"):
        return False, "Anime does not need metadata verification."

    stored_candidates = _metadata_review_candidates(anime)
    if not any(_metadata_candidate_key(candidate) == selection_key for candidate in stored_candidates if isinstance(candidate, dict)):
        return False, "Selected metadata candidate was not found."

    search_titles = anime.get("metadata_search_titles") if isinstance(anime.get("metadata_search_titles"), list) else []
    search_titles = [str(title) for title in search_titles if str(title or "").strip()]
    if not search_titles:
        search_titles = _metadata_search_titles(str(anime.get("title") or anime.get("original_title") or ""))
    try:
        results = _search_metadata_variants(search_titles)
    except MetadataProviderError as exc:
        return False, f"Metadata search failed: {exc}"

    selected = next((result for result in results if _metadata_result_key(result) == selection_key or _metadata_candidate_key(result) == selection_key), None)
    if selected is None:
        selected = next((candidate for candidate in stored_candidates if isinstance(candidate, dict) and _metadata_candidate_key(candidate) == selection_key), None)
    if selected is None:
        return False, "Selected metadata candidate could not be refreshed from providers."

    match_context = {
        "search_titles": search_titles,
        "year": _year_value(anime.get("metadata_year_hint")),
        "season_number": _season_hint_value(anime.get("metadata_season_hint")),
        "local_episode_count": _local_episode_count(anime),
    }
    _resolved_metadata_cache_store(match_context, selected)
    _apply_resolved_metadata(anime, selected, search_titles, "manual")
    _refresh_media_tag(anime)
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    _sync_anime_nfo_file(anime)
    _mark_torrent_search_pending(anime)
    message = f"Verified metadata for {anime.get('title', 'anime')}."
    _record_event(database, "metadata", message, anime)
    _write_user_database(database)
    return True, message



def _metadata_review_candidates(anime: dict[str, Any]) -> list[dict[str, Any]]:
    stored = anime.get("metadata_candidates") if isinstance(anime.get("metadata_candidates"), list) else []
    candidates = [candidate for candidate in stored if isinstance(candidate, dict)]
    search_titles = anime.get("metadata_search_titles") if isinstance(anime.get("metadata_search_titles"), list) else []
    search_titles = [str(title) for title in search_titles if str(title or "").strip()]
    if not search_titles:
        search_titles = _metadata_search_titles(str(anime.get("title") or anime.get("original_title") or ""))
    cached = _resolved_metadata_cache_lookup(
        {
            "search_titles": search_titles,
            "year": _year_value(anime.get("metadata_year_hint")),
            "season_number": _season_hint_value(anime.get("metadata_season_hint")),
            "local_episode_count": _local_episode_count(anime),
        }
    )
    if isinstance(cached, dict):
        cached_key = _metadata_candidate_key(cached)
        if cached_key and all(_metadata_candidate_key(candidate) != cached_key for candidate in candidates):
            candidates.insert(0, cached)
    return candidates
def _metadata_candidate_row(candidate: dict[str, Any]) -> dict[str, Any]:
    aliases = candidate.get("aliases") if isinstance(candidate.get("aliases"), list) else []
    return {
        "title": str(candidate.get("title") or "Unknown title"),
        "original_title": str(candidate.get("original_title") or "Unknown"),
        "year": str(candidate.get("year") or "Unknown"),
        "source": str(candidate.get("source") or "Unknown"),
        "aliases": [str(alias) for alias in aliases[:5]],
        "selection_key": _metadata_candidate_key(candidate),
    }


def _metadata_candidate_key(candidate: dict[str, Any]) -> str:
    if isinstance(candidate.get("provider_ids"), dict):
        return _metadata_result_key(candidate)
    return f"{candidate.get('source', '')}:{candidate.get('title', '')}:{candidate.get('year', '')}".casefold()

def _manual_candidate_row(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(candidate.get("title") or ""),
        "release_group": str(candidate.get("release_group") or "Unknown"),
        "release_kind": str(candidate.get("release_kind") or "Unknown"),
        "episode": candidate.get("episode") if candidate.get("episode") not in {None, ""} else "Batch",
        "size": str(candidate.get("size") or "Unknown"),
        "seeders": str(candidate.get("seeders") or 0),
        "detail_url": str(candidate.get("detail_url") or ""),
        "selection_key": _torrent_ignore_key(candidate),
        "confidence": int(candidate.get("confidence") or 0),
        "confidence_reasons": candidate.get("confidence_reasons") if isinstance(candidate.get("confidence_reasons"), list) else [],
    }

def _activity_queued_rows(database: dict[str, Any], *, include_client_snapshot: bool = False) -> list[dict[str, Any]]:
    rows = []
    client_snapshot = _download_client_existing_snapshot(database) if include_client_snapshot else {"keys": set(), "episodes_by_library_id": {}}
    for anime in database.get("anime", []):
        if not isinstance(anime, dict):
            continue
        if anime.get("monitored") is False:
            continue
        active_episodes: set[int] = set()
        active_episodes.update(_download_client_queued_episodes(anime, client_snapshot))
        for queue in _download_queue_items(anime):
            if queue.get("status") not in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged"}:
                continue
            if _queue_episode_is_local(anime, queue):
                continue
            episode = _int_value(queue.get("episode"))
            if episode is not None:
                active_episodes.add(episode)
            active_episodes.update(_queue_wanted_episode_numbers(queue))
            rows.append(_activity_row(anime, queue, include_completed=False))
        for episode in _missing_episode_numbers(anime):
            if episode not in active_episodes:
                rows.append(_activity_missing_episode_row(anime, episode, _resolved_episode_candidate(database, anime, episode)))
    return sorted(rows, key=lambda row: (row["sort_date"], row["anime"], row["episode"]), reverse=True)


def _activity_history_rows(database: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for anime in database.get("anime", []):
        if not isinstance(anime, dict):
            continue
        for queue in _download_queue_items(anime):
            if queue.get("status") not in {"completed", "imported"}:
                continue
            rows.append(_activity_row(anime, queue, include_completed=True))
    return sorted(rows, key=lambda row: row["sort_completed"] or row["sort_date"], reverse=True)


def _activity_blocked_rows(database: dict[str, Any]) -> list[dict[str, Any]]:
    ignored = database.get("ignored_torrents")
    if not isinstance(ignored, list):
        return []
    anime_by_id = {
        str(anime.get("library_id") or ""): anime
        for anime in database.get("anime", [])
        if isinstance(anime, dict)
    }
    rows = []
    for item in ignored:
        if not isinstance(item, dict):
            continue
        anime = anime_by_id.get(str(item.get("anime_library_id") or ""), {})
        rows.append(_activity_row(anime, item, include_completed=False, blocked=True))
    return sorted(rows, key=lambda row: row["sort_date"], reverse=True)


def _resolved_episode_candidate(database: dict[str, Any], anime: dict[str, Any], episode: int) -> dict[str, Any] | None:
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    usable = [
        candidate
        for candidate in _filter_ignored_torrent_candidates(database, candidates)
        if candidate.get("torrent_url")
        and candidate.get("release_kind") == "episode"
        and _int_value(candidate.get("episode")) == episode
    ]
    if not usable:
        return None
    return max(usable, key=lambda candidate: _candidate_selection_sort_key(candidate, database, anime))


def _activity_missing_episode_row(
    anime: dict[str, Any], episode: int, candidate: dict[str, Any] | None = None
) -> dict[str, Any]:
    resolved = isinstance(candidate, dict)
    return {
        "anime": str(anime.get("title") or anime.get("original_title") or "Unknown"),
        "episode": str(episode),
        "date_added": "Resolved" if resolved else "Wanted",
        "sort_date": "",
        "resolution": _activity_resolution_label(anime, {}),
        "time_left": "Dispatch pending" if resolved else "Waiting for torrent",
        "progress": 0,
        "date_completed": "",
        "sort_completed": "",
        "title": str(candidate.get("title") or "Resolved torrent") if resolved else "No torrent selected yet",
        "status": "resolved" if resolved else "wanted",
        "status_label": "Resolved · dispatch pending" if resolved else "Waiting for torrent",
        "status_tone": "resolved" if resolved else "wanted",
        "library_id": str(anime.get("library_id") or ""),
        "can_resolve": False,
    }

def _activity_row(
    anime: dict[str, Any],
    torrent: dict[str, Any],
    *,
    include_completed: bool,
    blocked: bool = False,
) -> dict[str, Any]:
    progress = _activity_progress(torrent)
    added_value = torrent.get("queued_at") or torrent.get("ignored_at") or torrent.get("rejected_at") or ""
    completed_value = torrent.get("completed_at") or ""
    status = str(torrent.get("status") or ("blocked" if blocked else ""))
    status_label, status_tone = _activity_status_pill(status)
    return {
        "anime": str(torrent.get("anime_title") or anime.get("title") or anime.get("original_title") or "Unknown"),
        "episode": _activity_episode_label(torrent),
        "date_added": _display_datetime_label(added_value),
        "sort_date": str(added_value),
        "resolution": _activity_resolution_label(anime, torrent),
        "time_left": _activity_time_left(torrent),
        "progress": progress,
        "date_completed": _display_datetime_label(completed_value) if include_completed else "",
        "sort_completed": str(completed_value),
        "title": str(torrent.get("title") or ""),
        "status": status,
        "status_label": status_label,
        "status_tone": status_tone,
        "library_id": str(anime.get("library_id") or torrent.get("anime_library_id") or ""),
        "can_resolve": not blocked and torrent.get("status") == "flagged",
        "can_unblock": blocked and bool(torrent.get("key")),
        "ignore_key": str(torrent.get("key") or ""),
    }


def _activity_status_pill(status: str) -> tuple[str, str]:
    labels = {
        "submitted": ("Submitted · awaiting client", "checking"),
        "queued": ("Checking client", "checking"),
        "pending_safety": ("Safety check", "checking"),
        "downloading": ("Downloading", "downloading"),
        "paused": ("Paused", "paused"),
        "stalled": ("Stalled", "stalled"),
        "error": ("Client error", "error"),
        "flagged": ("Needs review", "error"),
        "missing": ("Dispatch retry", "resolved"),
        "completed": ("Completed", "complete"),
        "imported": ("Imported", "complete"),
        "blocked": ("Blocked", "error"),
    }
    return labels.get(status, (status.replace("_", " ").title() or "Unknown", "wanted"))


def _activity_episode_label(torrent: dict[str, Any]) -> str:
    episode = torrent.get("episode")
    if episode not in {None, ""}:
        return str(episode)
    wanted = torrent.get("wanted_episodes")
    if isinstance(wanted, list) and wanted:
        if len(wanted) == 1:
            return str(wanted[0])
        return f"{wanted[0]}-{wanted[-1]}"
    return "Batch" if torrent.get("release_kind") == "batch" else "Unknown"


def _activity_resolution_label(anime: dict[str, Any], torrent: dict[str, Any]) -> str:
    for value in (anime.get("quality_resolution"), anime.get("quality_profile"), torrent.get("quality")):
        label = str(value or "").strip()
        if label:
            return label
    title = str(torrent.get("title") or "")
    for resolution in ("2160p", "1080p", "720p", "480p"):
        if resolution in title:
            return resolution
    return "Unknown"


def _activity_progress(torrent: dict[str, Any]) -> int:
    try:
        value = float(torrent.get("progress") or 0)
    except (TypeError, ValueError):
        return 0
    if 0 < value < 1:
        value *= 100
    elif value == 1 and torrent.get("status") in {"completed", "imported"}:
        value = 100
    return max(0, min(round(value), 100))


def _activity_time_left(torrent: dict[str, Any]) -> str:
    eta = torrent.get("eta")
    try:
        seconds = int(eta)
    except (TypeError, ValueError):
        return "Unknown"
    if seconds < 0 or seconds >= 8640000:
        return "Unknown"
    return _duration_label(seconds)


def _display_datetime_label(value: Any, settings: dict[str, Any] | None = None) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Unknown"
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return "Unknown"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return f"{parsed.astimezone(_display_timezone(settings)):%d %b %Y %H:%M} {display_timezone_label(settings)}"


def _duration_label(seconds: int) -> str:
    days, remainder = divmod(max(seconds, 0), 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def refresh_library_completion_state() -> dict[str, int]:
    database = _read_user_database()
    summary = _refresh_library_states(database["anime"], root_folder_configured=_root_folder_configured(database))
    _write_user_database(database)
    return summary


def refresh_library_media_tags(force: bool = False) -> dict[str, int]:
    database = _read_user_database()
    summary = _refresh_media_tags(database["anime"], force=force)
    _write_user_database(database)
    return summary


def _maybe_dispatch_torrent(database: dict[str, Any], anime: dict[str, Any], forced_release: dict[str, Any] | None = None) -> None:
    if anime.get("monitored") is False and forced_release is None:
        _append_torrent_notice(anime, "No automatic download was queued because this anime is unmonitored.")
        return
    completion = anime.get("completion") if isinstance(anime.get("completion"), dict) else {}
    if int(completion.get("missing_episodes") or 0) <= 0:
        _append_torrent_notice(anime, "No download was queued because all currently expected episodes are present.")
        return
    missing_episodes = _missing_episode_numbers(anime)

    root_folder = str(database.get("settings", {}).get("root_folder") or "").strip()
    if not root_folder:
        _append_torrent_notice(anime, "No download was queued because no anime root folder is configured.")
        return

    client_settings = database.get("settings", {}).get("download_client")
    if not isinstance(client_settings, dict) or client_settings.get("implementation") != "qbittorrent":
        _append_torrent_notice(anime, "No download was queued because qBittorrent is not configured.")
        return
    if not client_settings.get("enabled"):
        _append_torrent_notice(anime, "No download was queued because qBittorrent is disabled.")
        return

    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    releases = [forced_release] if forced_release is not None else _selected_download_releases(torrent_search.get("candidates"), database, anime)
    releases = [release for release in releases if isinstance(release, dict)]
    if not releases:
        if _manual_selection_required(anime):
            _append_torrent_notice(anime, "Manual torrent selection is required because candidate confidence is too low.")
        else:
            _append_torrent_notice(anime, "No download was queued because no suitable torrent candidate matched the selected resolution.")
        return

    deferred_release_count = max(0, len(releases) - MAX_TORRENT_DISPATCHES_PER_ANIME_TICK)
    releases = releases[:MAX_TORRENT_DISPATCHES_PER_ANIME_TICK]
    anime["torrent_dispatch_backlog"] = deferred_release_count > 0

    existing_queues = _download_queue_items(anime)
    existing_keys = _active_queue_identity_keys(anime)
    queued_episodes = _queued_episode_numbers(anime)
    queues = list(existing_queues)
    added = 0

    try:
        client = client_from_settings(database["settings"], timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS)
        category = str(client_settings.get("category") or "nyaarr")
        known_client_hashes = _current_client_hashes(client, category)
        tags = ",".join(filter(None, ["nyaarr", str(anime.get("library_id") or "")]))
        for release in releases:
            torrent_url = str(release.get("torrent_url") or "").strip()
            if not torrent_url:
                continue
            release_key = _queue_identity(release)
            episode = _int_value(release.get("episode"))
            if release_key and release_key in existing_keys:
                continue
            if release.get("release_kind") == "episode" and episode in queued_episodes:
                continue
            dispatch_save_path = _dispatch_save_path(anime, release, root_folder)
            add_visible = client.add_url(
                torrent_url,
                save_path=dispatch_save_path,
                category=category,
                tags=tags,
                paused=True,
                root_folder=release.get("release_kind") != "episode",
                expected_infohash=str(release.get("infohash") or ""),
            )
            if not str(release.get("infohash") or "").strip():
                discovered_hash = _new_client_hash(client, category, known_client_hashes)
                if discovered_hash:
                    release["infohash"] = discovered_hash
                    known_client_hashes.add(discovered_hash)
            queue = _download_queue_from_release(release, anime, client_settings, dispatch_save_path, missing_episodes)
            if add_visible is False:
                queue["status"] = "submitted"
                queue["message"] = "Submitted to qBittorrent; waiting for the expected torrent hash to become visible."
            else:
                _inspect_and_start_new_queue(database, client, anime, queue)
            release_group = str(release.get("release_group") or "")
            queue_group = str(queue.get("release_group") or "")
            lock_source = "torrent_files" if release_group in {"", "Unknown", "Manual"} and queue_group not in {"", "Unknown", "Manual"} else "queued"
            _set_release_group_lock_from_release(anime, queue, lock_source)
            queues.append(queue)
            if release_key:
                existing_keys.add(release_key)
            if release.get("release_kind") == "episode" and episode is not None:
                queued_episodes.add(episode)
            added += 1
    except QBittorrentError as exc:
        _append_torrent_notice(anime, f"qBittorrent dispatch failed: {exc}")
        return

    if not added:
        _sync_primary_download_queue(anime, queues)
        _append_torrent_notice(anime, "No download was queued because every suitable torrent is already queued.")
        return

    cleaned = _cleanup_episode_queues_covered_by_batch(database, client, anime, queues)
    _sync_primary_download_queue(anime, queues)
    anime["torrent_manual_selection"] = {"required": False}
    if cleaned:
        _append_torrent_notice(anime, f"Cleaned up {cleaned} individual episode torrent(s) now covered by a batch.")
    if deferred_release_count:
        _append_torrent_notice(
            anime,
            f"Deferred {deferred_release_count} resolved torrent(s) to the next local maintenance pass to protect qBittorrent.",
        )
    if added == 1:
        message = f"Sent {releases[0].get('title', 'selected torrent')} to qBittorrent."
        _append_torrent_notice(anime, message)
        _record_event(database, "torrent", message, anime, releases[0])
    else:
        message = f"Sent {added} missing episode torrents to qBittorrent."
        _append_torrent_notice(anime, message)
        _record_event(database, "torrent", message, anime)


def _inspect_and_start_new_queue(
    database: dict[str, Any], client: Any, anime: dict[str, Any], queue: dict[str, Any]
) -> None:
    torrent_hash = str(queue.get("hash") or "").strip().casefold()
    if not torrent_hash:
        queue["status"] = "pending_safety"
        queue["message"] = "Waiting for qBittorrent hash before safety inspection."
        return

    safety_result = _inspect_torrent_safety(client, torrent_hash, queue)
    if safety_result == "waiting":
        queue["status"] = "pending_safety"
        return
    if safety_result == "flagged":
        queue["status"] = "flagged"
        _record_event(database, "torrent", queue["message"], anime, queue)
        return

    if queue.get("select_batch_files") and queue.get("file_selection_status") != "applied":
        _apply_batch_file_selection(client, torrent_hash, queue)
        if queue.get("file_selection_status") != "applied":
            queue["status"] = "pending_safety"
            return

    if queue.get("user_add_paused"):
        queue["status"] = "paused"
        queue["message"] = "Torrent passed safety inspection and remains paused by setting."
        return

    try:
        client.resume(torrent_hash)
    except QBittorrentError as exc:
        queue["status"] = "error"
        queue["message"] = f"Torrent passed safety inspection, but qBittorrent start failed: {exc}"
        _record_event(database, "torrent", queue["message"], anime, queue)
        return
    queue["status"] = "queued"
    queue["message"] = "Torrent passed safety inspection and was started immediately."


def _current_client_hashes(client: Any, category: str) -> set[str]:
    try:
        torrents = client.torrents(category=category)
    except QBittorrentError:
        return set()
    return {str(torrent.get("hash") or "").casefold() for torrent in torrents if str(torrent.get("hash") or "").strip()}


def _new_client_hash(client: Any, category: str, known_hashes: set[str]) -> str:
    try:
        torrents = client.torrents(category=category)
    except QBittorrentError:
        return ""
    for torrent in torrents:
        torrent_hash = str(torrent.get("hash") or "").casefold()
        if torrent_hash and torrent_hash not in known_hashes:
            return torrent_hash
    return ""


def _cleanup_episode_queues_covered_by_batch(
    database: dict[str, Any],
    client: Any,
    anime: dict[str, Any],
    queues: list[dict[str, Any]] | None = None,
) -> int:
    queue_items = queues if queues is not None else _download_queue_items(anime)
    covered_episodes: set[int] = set()
    for queue in queue_items:
        if _queue_cleans_up_episode_torrents(queue):
            covered_episodes.update(_queue_wanted_episode_numbers(queue))
    if not covered_episodes:
        return 0

    cleaned = 0
    for queue in queue_items:
        if not _queue_is_active_episode_torrent(queue):
            continue
        episode = _int_value(queue.get("episode"))
        if episode not in covered_episodes:
            continue
        torrent_hash = str(queue.get("hash") or "").strip().casefold()
        try:
            if torrent_hash:
                client.delete(torrent_hash, delete_files=False)
        except QBittorrentError as exc:
            queue["status"] = "error"
            queue["message"] = f"Batch torrent covers episode {episode}, but qBittorrent cleanup failed: {exc}"
            _record_event(database, "torrent", queue["message"], anime, queue)
            continue

        queue["status"] = "superseded"
        queue["superseded_at"] = datetime.now(timezone.utc).isoformat()
        queue["message"] = f"Cleaned up individual episode {episode} torrent because a batch torrent now covers it."
        _record_event(database, "torrent", queue["message"], anime, queue)
        cleaned += 1
    return cleaned


def _queue_cleans_up_episode_torrents(queue: dict[str, Any]) -> bool:
    if queue.get("release_kind") != "batch" and not queue.get("select_batch_files"):
        return False
    return queue.get("status") in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged", "completed", "imported"}


def _queue_is_active_episode_torrent(queue: dict[str, Any]) -> bool:
    if queue.get("release_kind") not in {"", "episode", None}:
        return False
    if _int_value(queue.get("episode")) is None:
        return False
    return queue.get("status") in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged"}


def _queue_wanted_episode_numbers(queue: dict[str, Any]) -> set[int]:
    numbers: set[int] = set()
    episode = _int_value(queue.get("episode"))
    if episode is not None:
        numbers.add(episode)
    wanted = queue.get("wanted_episodes")
    if isinstance(wanted, list):
        numbers.update(number for number in (_int_value(value) for value in wanted) if number is not None)
    return numbers

def _dispatch_save_path(anime: dict[str, Any], release: dict[str, Any], root_folder: str) -> str:
    local_path = _existing_anime_local_path(anime)
    if release.get("release_kind") == "episode" and local_path:
        return local_path
    return root_folder


def _existing_anime_local_path(anime: dict[str, Any]) -> str:
    return str(anime.get("local_path") or "").strip()


def _target_folder_name(anime: dict[str, Any]) -> str:
    local_path = _existing_anime_local_path(anime)
    if local_path:
        return Path(local_path).name
    return _safe_folder_name(str(anime.get("title") or anime.get("original_title") or "Anime"))


def _download_queue_from_release(
    release: dict[str, Any],
    anime: dict[str, Any],
    client_settings: dict[str, Any],
    save_path: str,
    missing_episodes: list[int],
) -> dict[str, Any]:
    episode = _int_value(release.get("episode"))
    wanted_episodes = [episode] if release.get("release_kind") == "episode" and episode is not None else missing_episodes
    select_batch_files = release.get("release_kind") == "batch" and bool(missing_episodes)
    return {
        "status": "queued",
        "client": "qBittorrent",
        "category": str(client_settings.get("category") or "nyaarr"),
        "hash": str(release.get("infohash") or "").casefold(),
        "title": release.get("title", ""),
        "detail_url": release.get("detail_url", ""),
        "torrent_url": str(release.get("torrent_url") or ""),
        "release_kind": release.get("release_kind", ""),
        "release_group": release.get("release_group", ""),
        "episode": release.get("episode"),
        "confidence": release.get("confidence"),
        "confidence_reasons": release.get("confidence_reasons", []),
        "wanted_episodes": wanted_episodes,
        "select_batch_files": select_batch_files,
        "file_selection_status": "pending" if select_batch_files else "not_required",
        "autofill_from_torrent_files": bool(release.get("autofill_from_torrent_files")),
        "safety_status": "pending",
        "user_add_paused": bool(client_settings.get("add_paused")),
        "flagged_files": [],
        "save_path": save_path,
        "target_folder": _target_folder_name(anime),
        "queued_at": datetime.now(timezone.utc).isoformat(),
        "message": "Sent to qBittorrent paused for file safety inspection.",
    }


def _refresh_download_queue(database: dict[str, Any]) -> bool:
    queued_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
    changed = False
    for anime in database.get("anime", []):
        if not isinstance(anime, dict):
            continue
        anime_changed = False
        if _attach_existing_root_episode_files(database, anime):
            _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
            changed = True
            anime_changed = True
        for queue in _download_queue_items(anime):
            if _reconcile_locally_satisfied_queue(anime, queue):
                changed = True
                anime_changed = True
                continue
            if _queue_status_needs_refresh(queue):
                queued_items.append((anime, queue))
        if anime_changed:
            _sync_primary_download_queue(anime)
    if not queued_items:
        return changed

    try:
        client = client_from_settings(database["settings"], timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS)
    except QBittorrentError as exc:
        for anime, queue in queued_items:
            queue["message"] = f"qBittorrent status check failed: {exc}"
            _sync_primary_download_queue(anime)
        return True

    category = str(database.get("settings", {}).get("download_client", {}).get("category") or "nyaarr")
    try:
        torrents = client.torrents(category=category)
    except QBittorrentError as exc:
        for anime, queue in queued_items:
            queue["message"] = f"qBittorrent status check failed: {exc}"
            _sync_primary_download_queue(anime)
        return True
    torrents_by_hash = {str(torrent.get("hash") or "").casefold(): torrent for torrent in torrents}
    cleaned_anime_ids: set[str] = set()
    for anime, _queue in queued_items:
        anime_key = str(id(anime))
        if anime_key in cleaned_anime_ids:
            continue
        cleaned_anime_ids.add(anime_key)
        if _cleanup_episode_queues_covered_by_batch(database, client, anime):
            changed = True
            _sync_primary_download_queue(anime)
    for anime, queue in queued_items:
        if not _queue_status_needs_refresh(queue):
            continue
        was_missing = queue.get("status") == "missing"
        torrent_hash = str(queue.get("hash") or "").casefold()
        torrent = torrents_by_hash.get(torrent_hash)
        if torrent is None and torrent_hash:
            try:
                hash_matches = client.torrents(hashes=torrent_hash)
            except QBittorrentError:
                hash_matches = []
            torrent = next((item for item in hash_matches if str(item.get("hash") or "").casefold() == torrent_hash), None)
        if torrent is None and queue.get("status") == "submitted":
            submitted_at = _parse_datetime(queue.get("queued_at"))
            if submitted_at is not None and (datetime.now(timezone.utc) - submitted_at).total_seconds() < TORRENT_SUBMISSION_VISIBILITY_GRACE_SECONDS:
                queue["message"] = "Submitted to qBittorrent; waiting for the expected torrent hash to become visible."
                changed = True
                _sync_primary_download_queue(anime)
                continue
        if torrent is None:
            torrent = _torrent_from_queue_fallback(client, torrents, anime, queue)
            discovered_hash = str((torrent or {}).get("hash") or "").casefold()
            if discovered_hash:
                queue["hash"] = discovered_hash
                torrent_hash = discovered_hash
        if torrent is None:
            queue["status"] = "missing"
            queue["message"] = "Queued torrent is no longer visible in qBittorrent and will be searched again."
            _record_event(database, "torrent", queue["message"], anime, queue)
            changed = True
            _sync_primary_download_queue(anime)
            continue

        if was_missing and _torrent_ignore_key(queue) not in _ignored_torrent_keys(database):
            queue["unblocked_retry"] = True

        if _queue_uses_wrong_release_group(anime, queue):
            _delete_wrong_release_group_queue(database, client, anime, queue, torrent_hash)
            changed = True
            continue

        if _queue_needs_safety_inspection(queue, torrent):
            safety_result = _inspect_torrent_safety(client, torrent_hash, queue)
            changed = True
            if safety_result == "waiting":
                queue["status"] = "pending_safety"
                _sync_primary_download_queue(anime)
                continue
            if safety_result == "flagged":
                queue["status"] = "flagged"
                _record_event(database, "torrent", queue.get("message") or "Torrent failed safety inspection.", anime, queue)
                _sync_primary_download_queue(anime)
                continue
            if safety_result == "safe" and queue.get("user_add_paused"):
                queue["message"] = "Torrent passed safety inspection and remains paused by setting."
            _set_release_group_lock_from_release(anime, queue, 'torrent_files')

        progress = float(torrent.get("progress") or 0)
        client_state = str(torrent.get("state") or "")
        queue["client_state"] = client_state
        queue["status"] = _queue_status_from_client_state(client_state, progress)
        queue["progress"] = round(progress * 100)
        queue["message"] = _queue_message_from_client_state(client_state, queue["status"])
        queue["content_path"] = str(torrent.get("content_path") or "")
        queue["save_path"] = str(torrent.get("save_path") or queue.get("save_path") or "")
        if _relocate_episode_queue_to_local_folder(client, torrent_hash, anime, queue):
            changed = True
        queue["eta"] = torrent.get("eta")
        if _reconcile_locally_satisfied_queue(anime, queue):
            changed = True
            _sync_primary_download_queue(anime)
            continue
        if _resume_safe_paused_torrent(client, torrent_hash, queue):
            changed = True
        changed = True
        if queue.get("select_batch_files") and queue.get("file_selection_status") != "applied":
            if _apply_batch_file_selection(client, torrent_hash, queue):
                changed = True
        if progress >= 1:
            queue.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
            if _import_completed_torrent(anime, queue, database.get("settings", {}), client):
                queue["status"] = "imported"
                queue["message"] = "Completed torrent imported into the anime root folder."
                _record_event(database, "import", queue["message"], anime, queue)
                changed = True
        _sync_primary_download_queue(anime)
    return changed


def _queue_status_needs_refresh(queue: dict[str, Any]) -> bool:
    if queue.get("status") in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged", "completed", "imported"}:
        return True
    if queue.get("status") == "missing" and str(queue.get("hash") or "").strip():
        return True
    return bool(queue.get("status") == "missing" and (queue.get("select_batch_files") or queue.get("release_kind") == "batch") and not str(queue.get("hash") or "").strip())


def _reconcile_locally_satisfied_queue(anime: dict[str, Any], queue: dict[str, Any]) -> bool:
    if queue.get("status") not in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged"}:
        return False
    if not _queue_episode_is_local(anime, queue):
        return False
    changed = queue.get("status") != "imported" or queue.get("progress") != 100 or queue.get("import_status") != "imported"
    queue["status"] = "imported"
    queue["import_status"] = "imported"
    queue["progress"] = 100
    queue.setdefault("completed_at", datetime.now(timezone.utc).isoformat())
    queue["message"] = "Episode is already present in the anime root folder."
    return changed


def _queue_episode_is_local(anime: dict[str, Any], queue: dict[str, Any]) -> bool:
    local_episode_numbers = _local_episode_numbers(anime)
    episode = _int_value(queue.get("episode"))
    wanted = queue.get("wanted_episodes")
    wanted_numbers: set[int] = set()
    if isinstance(wanted, list):
        wanted_numbers = {number for number in (_int_value(value) for value in wanted) if number is not None}
    queue_episode_numbers = {episode} if episode is not None else wanted_numbers
    if queue_episode_numbers and queue_episode_numbers.issubset(local_episode_numbers):
        return True

    episode_files = anime.get("episode_files")
    if isinstance(episode_files, list):
        all_local_episode_numbers = _episode_numbers_from_file_paths(episode_files, None)
        if queue_episode_numbers:
            return queue_episode_numbers.issubset(all_local_episode_numbers)
        local_episode_numbers = local_episode_numbers or all_local_episode_numbers

    return bool(wanted_numbers) and wanted_numbers.issubset(local_episode_numbers)


def _torrent_from_queue_fallback(
    client: Any,
    torrents: list[dict[str, Any]],
    anime: dict[str, Any],
    queue: dict[str, Any],
) -> dict[str, Any] | None:
    if str(queue.get("hash") or "").strip():
        return None
    if queue.get("release_kind") != "batch" and not queue.get("select_batch_files"):
        return None

    candidates = []
    target = str(queue.get("target_folder") or anime.get("title") or anime.get("original_title") or "").strip().casefold()
    title = str(queue.get("title") or "").strip().casefold()
    for torrent in torrents:
        fields = " ".join(
            str(torrent.get(field) or "")
            for field in ("name", "content_path", "save_path")
        ).casefold()
        if title and title != "[manual]" and title in fields:
            candidates.append(torrent)
            continue
        if target and target in fields:
            candidates.append(torrent)

    if len(candidates) == 1:
        return candidates[0]
    return _torrent_from_queue_file_overlap(client, candidates, queue)


def _torrent_from_queue_file_overlap(client: Any, candidates: list[dict[str, Any]], queue: dict[str, Any]) -> dict[str, Any] | None:
    wanted = {
        int(episode)
        for episode in queue.get("wanted_episodes", [])
        if isinstance(episode, int) or str(episode).isdigit()
    }
    if not wanted:
        return None

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for torrent in candidates:
        torrent_hash = str(torrent.get("hash") or "").casefold()
        if not torrent_hash:
            continue
        try:
            files = client.torrent_files(torrent_hash)
        except QBittorrentError:
            continue
        episodes = {
            episode
            for file_info in files
            for episode in [episode_number_from_title(str(file_info.get("name") or ""))]
            if episode is not None
        }
        overlap = len(episodes & wanted)
        if overlap:
            scored.append((overlap, len(episodes), torrent))

    if not scored:
        return None
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0] and scored[0][1] == scored[1][1]:
        return None
    return scored[0][2]


def _queue_needs_safety_inspection(queue: dict[str, Any], torrent: dict[str, Any]) -> bool:
    safety_status = str(queue.get("safety_status") or "").strip().casefold()
    if safety_status == "pending":
        return True
    if safety_status in {"safe", "flagged", "allowed"}:
        return False

    queue_status = str(queue.get("status") or "").strip().casefold()
    client_state = str(torrent.get("state") or "").strip().casefold()
    if queue_status in {"queued", "paused", "pending_safety"}:
        return True
    return client_state.startswith("paused")


def _resume_safe_paused_torrent(client: Any, torrent_hash: str, queue: dict[str, Any]) -> bool:
    if queue.get("safety_status") != "safe":
        return False
    if queue.get("user_add_paused"):
        return False
    if queue.get("status") != "paused":
        return False
    if not torrent_hash:
        return False
    try:
        client.resume(torrent_hash)
    except QBittorrentError as exc:
        queue["message"] = f"Torrent passed safety inspection, but qBittorrent resume failed: {exc}"
        return True
    queue["message"] = "Torrent passed safety inspection and qBittorrent was resumed."
    return True


def _queue_release_group(queue: dict[str, Any]) -> str:
    group = str(queue.get("release_group") or "").strip()
    if group:
        return group
    return release_group_from_title(str(queue.get("title") or ""))


def _queue_uses_wrong_release_group(anime: dict[str, Any], queue: dict[str, Any]) -> bool:
    local_group = _local_release_group_preference(anime) or _locked_release_group(anime)
    queue_group = _queue_release_group(queue)
    if _queue_is_manual_supplied_batch(queue) or queue_group in {"Manual", "Unknown"}:
        return False
    return bool(
        local_group
        and queue_group
        and queue_group.casefold() != local_group.casefold()
    )


def _queue_is_manual_supplied_batch(queue: dict[str, Any]) -> bool:
    if queue.get("release_kind") != "batch" and not queue.get("select_batch_files"):
        return False
    if str(queue.get("title") or "").strip().casefold().startswith("[manual]"):
        return True
    reasons = queue.get("confidence_reasons")
    return isinstance(reasons, list) and any("provided while adding anime" in str(reason).casefold() for reason in reasons)


def _delete_wrong_release_group_queue(
    database: dict[str, Any],
    client: Any,
    anime: dict[str, Any],
    queue: dict[str, Any],
    torrent_hash: str,
) -> None:
    local_file_group = _local_release_group_preference(anime)
    locked_group = _locked_release_group(anime)
    local_group = local_file_group or locked_group
    queue_group = _queue_release_group(queue)
    try:
        if torrent_hash:
            client.delete(torrent_hash, delete_files=False)
    except QBittorrentError as exc:
        queue["status"] = "error"
        queue["message"] = f"Wrong release group {queue_group}; qBittorrent delete failed: {exc}"
        _record_event(database, "torrent", queue["message"], anime, queue)
        _sync_primary_download_queue(anime)
        return

    queue["status"] = "rejected"
    queue["rejected_at"] = datetime.now(timezone.utc).isoformat()
    reason = (
        f'existing episodes use {local_group}'
        if local_file_group
        else f'this anime is locked to {local_group}'
    )
    queue["message"] = f"Rejected {queue_group} release because {reason}. Searching for a matching subber."
    removed_files = _remove_wrong_release_group_imported_files(anime, queue)
    if removed_files:
        queue["removed_episode_files"] = removed_files
    _record_ignored_torrent(database, anime, queue)
    _record_event(database, "torrent", queue["message"], anime, queue)
    anime["torrent_search"] = {
        "query": str(anime.get("title") or anime.get("original_title") or ""),
        "strategy": "Queued for background torrent search",
        "candidates": [],
        "notices": [queue["message"]],
    }
    anime["torrent_manual_selection"] = {"required": False}
    _sync_primary_download_queue(anime)


def _remove_wrong_release_group_imported_files(anime: dict[str, Any], queue: dict[str, Any]) -> list[str]:
    # A release decision must never delete an existing library file. The file
    # remains available until the user performs a separate explicit cleanup.
    return []


def _import_completed_torrent(
    anime: dict[str, Any],
    queue: dict[str, Any],
    settings: dict[str, Any] | None = None,
    download_client: Any | None = None,
) -> bool:
    content_value = _mapped_download_path(queue.get("content_path"), settings or {}, queue)
    save_value = _mapped_download_path(queue.get("save_path"), settings or {}, queue)
    if not save_value:
        queue["import_status"] = "waiting_for_path"
        queue["message"] = "Completed torrent cannot be imported because qBittorrent did not report a save path."
        return False

    content_path = Path(content_value) if content_value else None
    save_path = Path(save_value)
    target_folder = _import_target_folder(anime, save_path)
    content_path = _normalize_completed_torrent_folder(download_client, queue, content_path, target_folder)
    source_paths: list[Path] = []
    if content_path is not None and content_path.exists():
        source_paths = _media_files(content_path) if content_path.is_dir() else [content_path]
        if _queue_imports_selected_batch_files(queue) and target_folder.exists():
            source_paths.extend(path for path in _media_files(target_folder) if path not in source_paths)
    elif target_folder.exists():
        source_paths = _media_files(target_folder)
    if not source_paths:
        queue["import_status"] = "waiting_for_files"
        queue["message"] = "Completed torrent files are not accessible from Nyaarr yet."
        return False

    importable_paths, rejected_paths = _validated_import_source_paths(anime, queue, source_paths)
    queue["rejected_import_files"] = rejected_paths
    _remove_rejected_files_from_renamed_folder(queue, rejected_paths)
    if not importable_paths:
        queue["import_status"] = "blocked"
        queue["message"] = "Completed torrent did not contain any media files matching wanted episodes."
        return False

    target_folder.mkdir(parents=True, exist_ok=True)
    imported_paths: list[str] = []
    for source_path in importable_paths:
        destination = target_folder / source_path.name
        if not _stage_imported_media_file(source_path, destination, queue):
            continue
        imported_paths.append(str(destination.resolve()))

    if not imported_paths:
        queue["import_status"] = "blocked"
        queue["message"] = "Completed torrent had no importable media files after validation."
        return False
    existing_files = [
        str(path)
        for path in anime.get("episode_files", [])
        if isinstance(path, str) and Path(path).exists()
    ]
    anime["local_path"] = str(target_folder.resolve())
    anime["episode_files"] = sorted(set(existing_files + imported_paths), key=str.casefold)
    queue["import_status"] = "imported"
    _refresh_media_tag(anime)
    _refresh_library_state(anime)
    _sync_anime_nfo_file(anime)
    return True


def _stage_imported_media_file(source_path: Path, destination: Path, queue: dict[str, Any]) -> bool:
    try:
        if source_path.resolve() == destination.resolve():
            return destination.exists()
    except OSError:
        return False

    if destination.exists():
        return True

    try:
        try:
            os.link(source_path, destination)
        except OSError:
            shutil.copy2(str(source_path), str(destination))
    except OSError as exc:
        queue["import_status"] = "waiting_for_files"
        queue["message"] = f"Could not preserve and stage selected media file in anime folder: {exc}"
        return False
    return True


def _queue_imports_selected_batch_files(queue: dict[str, Any]) -> bool:
    return bool(queue.get("select_batch_files") or queue.get("release_kind") == "batch")

def _import_target_folder(anime: dict[str, Any], save_path: Path) -> Path:
    local_path = _existing_anime_local_path(anime)
    if local_path:
        return Path(local_path)
    return save_path / _safe_folder_name(str(anime.get("title") or anime.get("original_title") or "Anime"))


def _normalize_completed_torrent_folder(
    download_client: Any | None,
    queue: dict[str, Any],
    content_path: Path | None,
    target_folder: Path,
) -> Path | None:
    if content_path is None or not content_path.exists() or not content_path.is_dir():
        return content_path
    if content_path.resolve() == target_folder.resolve():
        queue["normalized_folder"] = str(target_folder.resolve())
        return target_folder
    # Never rename a qBittorrent-owned content folder automatically. Importable
    # media is hardlinked or copied into the library while the original torrent
    # layout remains intact for verification and seeding.
    queue["folder_rename_status"] = "preserved_torrent_layout"
    return content_path


def _remove_rejected_files_from_renamed_folder(queue: dict[str, Any], rejected_paths: list[dict[str, str]]) -> None:
    # Validation may reject a file for import, but automatic validation never
    # owns or deletes torrent payload or existing library media.
    return


def _validated_import_source_paths(
    anime: dict[str, Any],
    queue: dict[str, Any],
    source_paths: list[Path],
) -> tuple[list[Path], list[dict[str, str]]]:
    wanted_episodes = _wanted_import_episodes(anime, queue)
    importable_paths: list[Path] = []
    rejected_paths: list[dict[str, str]] = []
    for source_path in source_paths:
        name = source_path.name
        extension = source_path.suffix.casefold()
        if extension not in MEDIA_EXTENSIONS:
            rejected_paths.append({"path": str(source_path), "reason": "not a supported media file"})
            continue
        if _looks_like_sample_file(source_path):
            rejected_paths.append({"path": str(source_path), "reason": "sample file"})
            continue
        episode = episode_number_from_title(name)
        if wanted_episodes and episode not in wanted_episodes:
            reason = "episode number could not be parsed" if episode is None else f"episode {episode} is not wanted"
            rejected_paths.append({"path": str(source_path), "reason": reason})
            continue
        importable_paths.append(source_path)
    return importable_paths, rejected_paths


def _wanted_import_episodes(anime: dict[str, Any], queue: dict[str, Any]) -> set[int]:
    wanted = {
        int(episode)
        for episode in queue.get("wanted_episodes", [])
        if isinstance(episode, int) or str(episode).isdigit()
    }
    episode = _int_value(queue.get("episode"))
    if episode is not None:
        wanted.add(episode)
    if not wanted:
        wanted.update(_missing_episode_numbers(anime))
    return wanted


def _looks_like_sample_file(path: Path) -> bool:
    parts = [part.casefold() for part in path.parts]
    stem = path.stem.casefold()
    return "sample" in parts or stem == "sample" or stem.endswith(" sample") or " sample " in f" {stem} "


def _relocate_episode_queue_to_local_folder(client: Any, torrent_hash: str, anime: dict[str, Any], queue: dict[str, Any]) -> bool:
    local_path = _existing_anime_local_path(anime)
    if not local_path or not torrent_hash:
        return False
    if queue.get("release_kind") not in {"episode", ""} and _int_value(queue.get("episode")) is None:
        return False
    if str(queue.get("status") or "") in {"rejected", "imported"}:
        return False
    current_save_path = str(queue.get("save_path") or "").strip()
    if _same_path_text(current_save_path, local_path):
        return False
    queue["relocation_status"] = "manual_review_required"
    queue["relocation_error"] = "Automatic qBittorrent relocation is disabled to protect existing library data."
    return False


def _same_path_text(left: str, right: str) -> bool:
    return bool(left and right and left.strip().replace("/", "\\").casefold() == right.strip().replace("/", "\\").casefold())


def _queue_status_from_client_state(client_state: str, progress: float) -> str:
    state = client_state.casefold()
    if progress >= 1:
        return "completed"
    if "error" in state or "missing" in state:
        return "error"
    if state.startswith("paused"):
        return "paused"
    if state.startswith("stalled"):
        return "stalled"
    if state in {"queueddown", "queuedup", "allocating", "metadl", "checkingdl", "checkingup", "checkingresume"}:
        return "queued"
    return "downloading"


def _queue_message_from_client_state(client_state: str, status: str) -> str:
    if status == "paused":
        return "Torrent is paused in qBittorrent."
    if status == "stalled":
        return "Torrent is stalled in qBittorrent."
    if status == "error":
        return "qBittorrent reported an error for this torrent."
    return client_state or status

def _mapped_download_path(value: Any, settings: dict[str, Any], queue: dict[str, Any]) -> str:
    path_value = str(value or "").strip()
    if not path_value:
        return ""

    client_settings = settings.get("download_client") if isinstance(settings.get("download_client"), dict) else {}
    for source in (queue, client_settings if isinstance(client_settings, dict) else {}):
        if not isinstance(source, dict) or not source.get("remote_path_mapping_enabled"):
            continue
        remote_path = str(source.get("remote_path") or "").strip().rstrip("\\/")
        local_path = str(source.get("local_path") or "").strip().rstrip("\\/")
        if not remote_path or not local_path:
            continue
        comparable_path = path_value.replace("\\", "/")
        comparable_remote = remote_path.replace("\\", "/")
        if comparable_path.casefold() == comparable_remote.casefold():
            return local_path
        prefix = comparable_remote.rstrip("/") + "/"
        if comparable_path.casefold().startswith(prefix.casefold()):
            suffix = comparable_path[len(prefix):].replace("/", os.sep)
            return str(Path(local_path) / suffix)
    return path_value

def _selected_download_release(
    candidates: Any,
    database: dict[str, Any] | None = None,
    anime: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    releases = _selected_download_releases(candidates, database, anime)
    return releases[0] if releases else None


def _selected_download_releases(
    candidates: Any,
    database: dict[str, Any] | None = None,
    anime: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(candidates, list) or anime is None:
        return []
    ignored_keys = _ignored_torrent_keys(database or {})
    allows_bluray = _quality_resolution(anime or {}) == "BD"
    missing_episodes = _missing_episode_numbers(anime)
    queued_episodes = _queued_episode_numbers(anime)
    client_snapshot = _download_client_existing_snapshot(database or {})
    queued_episodes.update(_download_client_queued_episodes(anime, client_snapshot))
    queued_keys = _active_queue_identity_keys(anime)
    queued_keys.update(client_snapshot.get("keys", set()))
    scored: list[dict[str, Any]] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if candidate.get("source_kind") == "bluray" and not allows_bluray:
            continue
        if _torrent_ignore_key(candidate) in ignored_keys:
            continue
        if not candidate.get("torrent_url"):
            continue
        if candidate.get("release_kind") == "batch" and _explicit_ongoing_anime(anime):
            verification = candidate.get("batch_verification")
            if not isinstance(verification, dict) or verification.get("status") != "verified":
                continue
        candidate_episode = _int_value(candidate.get("episode"))
        if missing_episodes and candidate.get("release_kind") == "episode":
            if candidate_episode not in missing_episodes or candidate_episode in queued_episodes:
                continue
        if _queue_identity(candidate) in queued_keys:
            continue
        candidate = dict(candidate)
        score, reasons = _torrent_candidate_confidence(candidate, database or {}, anime)
        candidate["confidence"] = score
        candidate["confidence_reasons"] = reasons
        scored.append(candidate)
    if not scored:
        _set_no_usable_torrent_candidates(anime)
        return []
    scored.sort(key=lambda item: _candidate_selection_sort_key(item, database or {}, anime), reverse=True)
    best = scored[0]
    threshold = _torrent_confidence_threshold(database or {})
    if int(best.get("confidence") or 0) < threshold:
        _set_manual_selection_required(
            anime,
            int(best.get("confidence") or 0),
            f"Best torrent confidence is below {threshold}.",
            str(best.get("title") or ""),
        )
        return []
    anime["torrent_manual_selection"] = {"required": False}
    if best.get("release_kind") != "episode":
        return [best]
    preferred_group = str(best.get("release_group") or "Unknown")
    episode_releases = [
        release
        for release in scored
        if release.get("release_kind") == "episode"
        and str(release.get("release_group") or "Unknown") == preferred_group
        and _int_value(release.get("episode")) not in queued_episodes
    ]
    best_by_episode: dict[int, dict[str, Any]] = {}
    for release in episode_releases:
        episode = _int_value(release.get("episode"))
        if episode is None:
            continue
        existing = best_by_episode.get(episode)
        if existing is None or _candidate_selection_sort_key(release, database or {}, anime) > _candidate_selection_sort_key(existing, database or {}, anime):
            best_by_episode[episode] = release
    return [best_by_episode[episode] for episode in sorted(best_by_episode)]


def _candidate_selection_sort_key(candidate: dict[str, Any], database: dict[str, Any], anime: dict[str, Any] | None = None) -> tuple[int, int, int, int, int, int]:
    return (
        _candidate_locked_release_group_rank(candidate, anime or {}),
        _candidate_preferred_subber_rank(candidate, database),
        _audio_preference_rank(candidate),
        _candidate_release_group_source_rank(candidate),
        int(candidate.get("confidence") or 0),
        int(candidate.get("seeders") or 0),
    )


def _candidate_locked_release_group_rank(candidate: dict[str, Any], anime: dict[str, Any]) -> int:
    locked_group = _preferred_release_group_for_anime(anime).casefold()
    release_group = str(candidate.get("release_group") or "").strip().casefold()
    return 1 if locked_group and release_group == locked_group else 0


def _candidate_preferred_subber_rank(candidate: dict[str, Any], database: dict[str, Any]) -> int:
    release_group = str(candidate.get("release_group") or "").strip().casefold()
    return 1 if release_group and release_group in _preferred_subbers(database) else 0


def _candidate_release_group_source_rank(candidate: dict[str, Any]) -> int:
    source = str(candidate.get("release_group_source") or "").strip().casefold()
    if not source:
        title = str(candidate.get("title") or "")
        if re.match(r"^\s*\[[^\]]+\]", title):
            source = "prefix"
        elif _suffix_release_group_from_title(title):
            source = "suffix"
    return {"prefix": 2, "suffix": 1}.get(source, 0)


def _suffix_release_group_from_title(title: str) -> str:
    value = re.sub(r"\.(?:mkv|mp4|avi|m2ts|mov|webm)\s*$", "", title.strip(), flags=re.IGNORECASE)
    while True:
        stripped = re.sub(r"\s+(?:\[[^\]]+\]|\([^)]*\))\s*$", "", value).strip()
        if stripped == value:
            break
        value = stripped
    match = re.search(
        r"(?:x26[45]|h\.?\s*26[45]|hevc|av1|web[-\s]?dl|webrip|bdrip|hdtv)[^-]{0,100}-([A-Za-z0-9][A-Za-z0-9._+]{1,31})$",
        value,
        flags=re.IGNORECASE,
    )
    if not match:
        return ""
    group = match.group(1).strip(" ._-")
    return "" if group.casefold() in {"dl", "rip", "sub", "subs", "multi", "dual", "audio"} else group


def _torrent_candidate_confidence(candidate: dict[str, Any], database: dict[str, Any], anime: dict[str, Any]) -> tuple[int, list[str]]:
    score = 40
    reasons = ["candidate has a torrent URL"]
    preferred_resolution = _quality_resolution(anime)
    title = str(candidate.get("title") or "")
    title_match = _candidate_title_match(candidate, anime)
    if not title_match:
        score -= 50
        reasons.append("torrent title does not match the selected anime title")
    elif title_match[0] in {"alias", "romaji", "metadata"}:
        score += 8
        reasons.append(f"torrent title matches anime {title_match[0]} title {title_match[1]}")
    if preferred_resolution == "BD" and candidate.get("source_kind") == "bluray":
        score += 15
        reasons.append("matches BD preference")
    elif preferred_resolution != "BD" and preferred_resolution.casefold() in title.casefold():
        score += 15
        reasons.append(f"matches {preferred_resolution} preference")
    missing_episodes = _missing_episode_numbers(anime)
    local_count = _local_episode_count(anime)
    if candidate.get("release_kind") == "batch" and candidate.get("batch_fallback_episodes"):
        score += 15
        reasons.append("same-subber batch can target stalled or low-seed missing episodes")
    elif local_count == 0 and candidate.get("release_kind") == "batch":
        score += 12
        reasons.append("batch fits empty local library")
    elif candidate.get("release_kind") == "episode" and (not missing_episodes or candidate.get("episode") in missing_episodes):
        score += 15
        reasons.append("episode matches missing episode")
    release_group = str(candidate.get("release_group") or "").strip()
    local_release_group = _preferred_release_group_for_anime(anime)
    if local_release_group and release_group.casefold() == local_release_group.casefold():
        score += 18
        reasons.append(f"matches existing local release group {local_release_group}")
    elif local_release_group and release_group and release_group != "Unknown":
        score -= 5
        reasons.append(f"does not match existing local release group {local_release_group}")
    preferred_subbers = _preferred_subbers(database)
    if preferred_subbers and release_group.casefold() in preferred_subbers:
        score += 15
        reasons.append("release group is prioritized")
    try:
        seeders = int(candidate.get("seeders") or 0)
    except (TypeError, ValueError):
        seeders = 0
    if seeders >= 20:
        score += 8
        reasons.append("healthy seed count")
    elif seeders >= 5:
        score += 5
        reasons.append("usable seed count")
    elif seeders <= 0:
        score -= 10
        reasons.append("no seeders reported")
    if release_group and release_group != "Unknown":
        score += 5
        reasons.append("release group is known")
    else:
        score -= 5
        reasons.append("release group is unknown")
    return max(0, min(score, 100)), reasons


def _candidate_title_matches_anime(candidate: dict[str, Any], anime: dict[str, Any]) -> bool:
    return bool(_candidate_title_match(candidate, anime))


def _candidate_title_match(candidate: dict[str, Any], anime: dict[str, Any]) -> tuple[str, str] | None:
    title = str(candidate.get("title") or "").strip()
    if not title or str(candidate.get("category") or "") == "Manual":
        return ("manual", "")
    seen = set()
    for source, anime_title in _anime_confidence_title_values(anime):
        key = anime_title.casefold()
        if key in seen:
            continue
        seen.add(key)
        if torrent_title_matches(anime_title, title):
            return source, anime_title
    return None


def _anime_confidence_title_values(anime: dict[str, Any]) -> list[tuple[str, str]]:
    values: list[tuple[str, Any]] = [
        ("selected", anime.get("title")),
        ("romaji", anime.get("original_title")),
        ("romaji", anime.get("romaji_title")),
        ("selected", anime.get("english_title")),
        ("alias", anime.get("native_title")),
    ]
    metadata_titles = anime.get("metadata_search_titles")
    if isinstance(metadata_titles, list):
        values.extend(("metadata", value) for value in metadata_titles)
    aliases = anime.get("aliases")
    if isinstance(aliases, list):
        values.extend(("alias", value) for value in aliases)
    provider_title = anime.get("provider_title")
    if isinstance(provider_title, dict):
        values.extend(
            [
                ("romaji", provider_title.get("romaji")),
                ("selected", provider_title.get("english")),
                ("alias", provider_title.get("native")),
            ]
        )
    titles: list[tuple[str, str]] = []
    for source, value in values:
        title = str(value or "").strip()
        if title:
            titles.append((source, title))
    return titles


def _manual_torrent_release(anime: dict[str, Any], torrent_link: str, episode: str = "") -> tuple[dict[str, Any], str]:
    link = str(torrent_link or "").strip()
    if not link:
        return {}, "Enter a magnet link or torrent URL."
    if not _is_supported_manual_torrent_link(link):
        return {}, "Manual torrent links must be magnet links or http(s) .torrent/Nyaa URLs."
    episode_number = _int_value(episode)
    if episode_number is None:
        missing = _missing_episode_numbers(anime)
        episode_number = missing[0] if len(missing) == 1 else None
    infohash = _magnet_infohash(link)
    title = _manual_torrent_title(anime, episode_number, link)
    release_group = release_group_from_title(title)
    if release_group == "Unknown":
        release_group = "Manual"
    return {
        "library_id": str(anime.get("library_id") or ""),
        "title": title,
        "detail_url": _manual_torrent_detail_url(link),
        "torrent_url": _manual_torrent_download_url(link),
        "guid": link,
        "published": "",
        "seeders": 0,
        "leechers": 0,
        "downloads": 0,
        "infohash": infohash,
        "category": "Manual",
        "category_id": "manual",
        "size": "Unknown",
        "size_bytes": 0,
        "trusted": "No",
        "remake": "No",
        "release_group": release_group,
        "release_kind": "episode" if episode_number is not None else "batch",
        "episode": episode_number,
        "source_kind": "unknown",
        "resolution": None,
    }, ""


def _is_supported_manual_torrent_link(link: str) -> bool:
    normalized = link.casefold()
    if normalized.startswith("magnet:?"):
        return bool(_magnet_infohash(link))
    if not normalized.startswith(("http://", "https://")):
        return False
    parsed = urllib.parse.urlparse(link)
    if parsed.netloc.casefold().endswith("nyaa.si") and re.search(r"/(?:view|download)/\d+", parsed.path):
        return True
    return parsed.path.casefold().endswith(".torrent")


def _magnet_infohash(link: str) -> str:
    if not link.casefold().startswith("magnet:?"):
        return ""
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    for value in parsed.get("xt", []):
        match = re.fullmatch(r"urn:btih:([A-Fa-f0-9]{32,40})", value.strip())
        if match:
            return match.group(1).casefold()
    return ""


def _manual_torrent_download_url(link: str) -> str:
    match = re.search(r"https?://(?:www\.)?nyaa\.si/view/(\d+)", link, flags=re.IGNORECASE)
    if match:
        return f"https://nyaa.si/download/{match.group(1)}.torrent"
    return link


def _manual_torrent_detail_url(link: str) -> str:
    match = re.search(r"https?://(?:www\.)?nyaa\.si/download/(\d+)\.torrent", link, flags=re.IGNORECASE)
    if match:
        return f"https://nyaa.si/view/{match.group(1)}"
    return "" if link.casefold().startswith("magnet:?") else link


def _manual_torrent_title(anime: dict[str, Any], episode: int | None, link: str) -> str:
    title = str(anime.get("title") or anime.get("original_title") or "Manual torrent").strip() or "Manual torrent"
    if link.casefold().startswith("magnet:?"):
        display_names = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("dn", [])
        if display_names and display_names[0].strip():
            return display_names[0].strip()
    if episode is not None:
        return f"[Manual] {title} - {episode:02d}"
    return f"[Manual] {title}"

def _set_release_group_lock_from_release(anime: dict[str, Any], release: dict[str, Any], source: str) -> None:
    group = str(release.get("release_group") or "").strip() or release_group_from_title(str(release.get("title") or ""))
    _set_release_group_lock(anime, group, source)


def _set_release_group_lock(anime: dict[str, Any], group: str, source: str) -> None:
    release_group = str(group or "").strip()
    if not release_group or release_group in {"Unknown", "Manual"}:
        return
    existing = _locked_release_group(anime)
    if existing and existing.casefold() != release_group.casefold():
        return
    anime["release_group_lock"] = {
        "release_group": release_group,
        "source": str(source or "automatic"),
        "locked_at": datetime.now(timezone.utc).isoformat(),
    }


def _locked_release_group(anime: dict[str, Any]) -> str:
    lock = anime.get("release_group_lock")
    if isinstance(lock, dict):
        group = str(lock.get("release_group") or "").strip()
    else:
        group = str(anime.get("locked_release_group") or anime.get("preferred_release_group") or "").strip()
    return "" if group in {"Unknown", "Manual"} else group

def _preferred_release_group_for_anime(anime: dict[str, Any]) -> str:
    local_group = _local_release_group_preference(anime)
    if local_group:
        return local_group
    locked_group = _locked_release_group(anime)
    if locked_group:
        return locked_group
    groups = []
    for queue in _download_queue_items(anime):
        if queue.get("status") not in {"queued", "downloading", "paused", "stalled", "pending_safety", "completed", "imported"}:
            continue
        group = _queue_release_group(queue)
        if group and group != "Unknown" and group != "Manual":
            groups.append(group)
    return Counter(groups).most_common(1)[0][0] if groups else ""


def _local_release_group_preference(anime: dict[str, Any]) -> str:
    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list):
        return ""
    groups = []
    for episode_file in episode_files:
        group = release_group_from_title(Path(str(episode_file or "")).name)
        if group and group != "Unknown":
            groups.append(group)
    if not groups:
        return ""
    return Counter(groups).most_common(1)[0][0]

def _preferred_subbers(database: dict[str, Any]) -> set[str]:
    return {subber.casefold() for subber in _preferred_subber_list(database)}


def _preferred_subber_list(database: dict[str, Any]) -> list[str]:
    settings = database.get("settings") if isinstance(database.get("settings"), dict) else {}
    return _normalized_preferred_subbers(settings.get("preferred_subbers") if isinstance(settings, dict) else None)


def _normalized_preferred_subbers(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_values = re.split(r"[,\n]", value)
    elif isinstance(value, list):
        raw_values = value
    else:
        raw_values = []
    preferred: list[str] = []
    seen: set[str] = set()
    for item in [*DEFAULT_PREFERRED_SUBBERS, *raw_values]:
        subber = str(item or "").strip()
        key = subber.casefold()
        if not subber or key in seen:
            continue
        preferred.append(subber)
        seen.add(key)
    return preferred or list(DEFAULT_PREFERRED_SUBBERS)


def _posted_confidence_threshold(value: Any) -> int | None:
    try:
        threshold = int(str(value or "").strip())
    except ValueError:
        return None
    return threshold if 1 <= threshold <= 100 else None


def _torrent_confidence_threshold(database: dict[str, Any]) -> int:
    settings = database.get("settings") if isinstance(database.get("settings"), dict) else {}
    threshold = _posted_confidence_threshold(settings.get("torrent_confidence_threshold") if isinstance(settings, dict) else None)
    return threshold if threshold is not None else 70


def _set_manual_selection_required(
    anime: dict[str, Any],
    confidence: int,
    reason: str,
    best_candidate_title: str,
    *,
    intervention_type: str = "candidate_review",
) -> None:
    anime["torrent_manual_selection"] = {
        "required": True,
        "confidence": confidence,
        "reason": reason,
        "best_candidate_title": best_candidate_title,
        "intervention_type": intervention_type,
        "flagged_at": datetime.now(timezone.utc).isoformat(),
    }


def _manual_selection_required(anime: dict[str, Any]) -> bool:
    manual = anime.get("torrent_manual_selection")
    if not isinstance(manual, dict) or not manual.get("required"):
        return False
    if str(manual.get("intervention_type") or "") == "no_candidates":
        return True
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    return bool(candidates)


def _clear_stale_manual_selection(anime: dict[str, Any]) -> bool:
    manual = anime.get("torrent_manual_selection")
    if not isinstance(manual, dict) or not manual.get("required"):
        return False
    if str(manual.get("intervention_type") or "") == "no_candidates":
        return False
    torrent_search = anime.get("torrent_search") if isinstance(anime.get("torrent_search"), dict) else {}
    candidates = torrent_search.get("candidates") if isinstance(torrent_search.get("candidates"), list) else []
    if candidates:
        return False
    anime["torrent_manual_selection"] = {"required": False}
    return True


def _quality_resolution(anime: dict[str, Any]) -> str:
    value = str(anime.get("quality_resolution") or anime.get("quality_profile") or "1080p").strip().casefold()
    if "bd" in value or "blu" in value:
        return "BD"
    if "720" in value:
        return "720p"
    return "1080p"


def _quality_profile_label(anime: dict[str, Any]) -> str:
    return f"Up to: {_quality_resolution(anime)}"


def _inspect_torrent_safety(client: Any, torrent_hash: str, queue: dict[str, Any]) -> str:
    try:
        files = client.torrent_files(torrent_hash)
    except QBittorrentError as exc:
        queue["message"] = f"Waiting for qBittorrent file metadata before safety inspection: {exc}"
        return "waiting"

    if not files:
        queue["message"] = "Waiting for qBittorrent file metadata before safety inspection."
        return "waiting"

    flagged_files = []
    for file_info in files:
        name = str(file_info.get("name") or "")
        extension = Path(name).suffix.casefold()
        if extension in MEDIA_EXTENSIONS:
            continue
        if _queue_allows_batch_sidecars(queue) and (extension not in DANGEROUS_TORRENT_EXTENSIONS or extension == ".url"):
            continue
        flagged_files.append(
            {
                "name": name,
                "extension": extension or "[none]",
                "reason": (
                    "Dangerous extension"
                    if extension in DANGEROUS_TORRENT_EXTENSIONS
                    else "Not an anime video file"
                ),
            }
        )

    if flagged_files:
        queue["safety_status"] = "flagged"
        queue["flagged_files"] = flagged_files
        queue["message"] = f"Flagged torrent: {len(flagged_files)} non-video or dangerous file(s) found."
        return "flagged"

    detected_groups = [
        release_group_from_title(Path(str(file_info.get("name") or "")).name)
        for file_info in files
        if Path(str(file_info.get("name") or "")).suffix.casefold() in MEDIA_EXTENSIONS
    ]
    detected_groups = [group for group in detected_groups if group not in {"", "Unknown", "Manual"}]
    if detected_groups and str(queue.get("release_group") or "") in {"", "Unknown", "Manual"}:
        queue["release_group"] = Counter(detected_groups).most_common(1)[0][0]

    if queue.get("autofill_from_torrent_files"):
        _autofill_queue_from_torrent_files(queue, files)

    queue["safety_status"] = "safe"
    queue["flagged_files"] = []
    queue["message"] = "Torrent passed safety inspection."
    return "safe"


def _queue_allows_batch_sidecars(queue: dict[str, Any]) -> bool:
    return bool(queue.get("select_batch_files") or queue.get("autofill_from_torrent_files") or queue.get("release_kind") == "batch")


def _autofill_queue_from_torrent_files(queue: dict[str, Any], files: list[dict[str, Any]]) -> None:
    media: list[tuple[int | None, str, str]] = []
    for file_info in files:
        name = str(file_info.get("name") or "")
        if Path(name).suffix.casefold() not in MEDIA_EXTENSIONS:
            continue
        media.append((episode_number_from_title(name), name, release_group_from_title(Path(name).name)))
    parsed_episodes = sorted({episode for episode, _name, _group in media if episode is not None and episode > 0})
    groups = [group for _episode, _name, group in media if group and group != "Unknown"]
    if groups:
        queue["release_group"] = Counter(groups).most_common(1)[0][0]
    if len(media) == 1 and media[0][0] is not None:
        episode = media[0][0]
        queue["release_kind"] = "episode"
        queue["episode"] = episode
        queue["wanted_episodes"] = [episode]
        queue["select_batch_files"] = False
        queue["file_selection_status"] = "not_required"
    elif parsed_episodes:
        planned_wanted = {
            int(episode)
            for episode in queue.get("wanted_episodes", [])
            if isinstance(episode, int) or str(episode).isdigit()
        }
        wanted_episodes = [episode for episode in parsed_episodes if not planned_wanted or episode in planned_wanted]
        queue["release_kind"] = "batch"
        queue["episode"] = None
        queue["torrent_file_episodes"] = parsed_episodes
        queue["wanted_episodes"] = wanted_episodes or parsed_episodes
        queue["select_batch_files"] = True
        if queue.get("file_selection_status") in {"not_required", "applied"}:
            queue["file_selection_status"] = "pending"
    queue["autofilled_episodes"] = parsed_episodes
    queue["autofill_from_torrent_files"] = False


def _apply_batch_file_selection(client: Any, torrent_hash: str, queue: dict[str, Any]) -> bool:
    wanted_episodes = {
        int(episode)
        for episode in queue.get("wanted_episodes", [])
        if isinstance(episode, int) or str(episode).isdigit()
    }
    if not wanted_episodes:
        queue["file_selection_status"] = "not_required"
        return True

    try:
        files = client.torrent_files(torrent_hash)
    except QBittorrentError as exc:
        queue["file_selection_status"] = "waiting_for_metadata"
        queue["message"] = f"Waiting for qBittorrent batch file metadata: {exc}"
        return True

    if not files:
        queue["file_selection_status"] = "waiting_for_metadata"
        queue["message"] = "Waiting for qBittorrent batch file metadata."
        return True

    keep_indexes: list[int] = []
    skip_indexes: list[int] = []
    selected_files: list[dict[str, Any]] = []
    skipped_unparsed = 0
    skipped_samples = 0
    skipped_sidecars = 0
    for position, file_info in enumerate(files):
        index = _torrent_file_index(file_info, position)
        name = str(file_info.get("name") or "")
        extension = Path(name).suffix.casefold()
        if extension not in MEDIA_EXTENSIONS:
            skip_indexes.append(index)
            skipped_sidecars += 1
            continue
        if _looks_like_sample_file(Path(name)):
            skip_indexes.append(index)
            skipped_samples += 1
            continue
        episode = episode_number_from_title(name)
        if episode in wanted_episodes:
            keep_indexes.append(index)
            selected_files.append({"episode": episode, "index": index, "name": name})
        else:
            skip_indexes.append(index)
            if episode is None:
                skipped_unparsed += 1

    try:
        client.set_file_priority(torrent_hash, skip_indexes, 0)
        client.set_file_priority(torrent_hash, keep_indexes, 1)
    except QBittorrentError as exc:
        queue["file_selection_status"] = "failed"
        queue["message"] = f"qBittorrent batch file selection failed: {exc}"
        return True

    queue["file_selection_status"] = "applied"
    queue["selected_file_count"] = len(keep_indexes)
    queue["skipped_file_count"] = len(skip_indexes)
    queue["selected_episode_files"] = selected_files
    queue["message"] = (
        f"Selected {len(keep_indexes)} missing episode files from batch."
        if keep_indexes
        else "No matching missing episode files were found in batch."
    )
    details = []
    if skipped_samples:
        details.append(f"{skipped_samples} sample file(s)")
    if skipped_sidecars:
        details.append(f"{skipped_sidecars} sidecar file(s)")
    if skipped_unparsed:
        details.append(f"{skipped_unparsed} media file(s) with unparsed episode numbers")
    if details:
        queue["message"] += " Skipped " + ", ".join(details) + "."
    return True


def _torrent_file_index(file_info: dict[str, Any], fallback: int) -> int:
    try:
        return int(file_info.get("index", fallback))
    except (TypeError, ValueError):
        return fallback


def _download_client_existing_snapshot(database: dict[str, Any]) -> dict[str, Any]:
    settings = database.get("settings") if isinstance(database.get("settings"), dict) else {}
    client_settings = settings.get("download_client") if isinstance(settings, dict) else {}
    if not isinstance(client_settings, dict) or client_settings.get("implementation") != "qbittorrent" or not client_settings.get("enabled"):
        return {"keys": set(), "episodes_by_library_id": {}}
    try:
        client = client_from_settings(settings, timeout=DOWNLOAD_CLIENT_TIMEOUT_SECONDS)
        torrents = client.torrents(category=str(client_settings.get("category") or "nyaarr"))
    except QBittorrentError:
        return {"keys": set(), "episodes_by_library_id": {}}

    keys = {_download_client_torrent_key(torrent) for torrent in torrents if _download_client_torrent_key(torrent)}
    episodes_by_library_id: dict[str, set[int]] = {}
    for anime in database.get("anime", []):
        if not isinstance(anime, dict):
            continue
        library_id = str(anime.get("library_id") or "")
        if not library_id:
            continue
        episodes = set()
        for torrent in torrents:
            for torrent_name in _download_client_torrent_names(torrent):
                if not torrent_name or not _torrent_name_matches_anime(anime, torrent_name):
                    continue
                episode = episode_number_from_title(torrent_name)
                if episode is not None:
                    episodes.add(episode)
                    break
        if episodes:
            episodes_by_library_id[library_id] = episodes
    return {"keys": keys, "episodes_by_library_id": episodes_by_library_id}


def _candidate_already_in_download_client(candidate: dict[str, Any], anime: dict[str, Any], snapshot: dict[str, Any]) -> bool:
    candidate_key = _queue_identity(candidate)
    if candidate_key and candidate_key in snapshot.get("keys", set()):
        return True
    episode = _int_value(candidate.get("episode"))
    return episode is not None and episode in _download_client_queued_episodes(anime, snapshot)


def _download_client_queued_episodes(anime: dict[str, Any], snapshot: dict[str, Any]) -> set[int]:
    episodes_by_library_id = snapshot.get("episodes_by_library_id")
    if not isinstance(episodes_by_library_id, dict):
        return set()
    episodes = episodes_by_library_id.get(str(anime.get("library_id") or ""), set())
    return set(episodes) if isinstance(episodes, set) else set()


def _download_client_torrent_key(torrent: dict[str, Any]) -> str:
    torrent_hash = str(torrent.get("hash") or "").strip().casefold()
    if torrent_hash:
        return f"hash:{torrent_hash}"
    names = _download_client_torrent_names(torrent)
    return _queue_identity({"title": names[0] if names else ""})


def _download_client_torrent_names(torrent: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for field in ("content_path", "name"):
        value = str(torrent.get(field) or "").strip()
        if value:
            name = Path(value).name
            if name and name not in names:
                names.append(name)
    names.sort(key=lambda value: episode_number_from_title(value) is None)
    return names


def _torrent_name_matches_anime(anime: dict[str, Any], torrent_name: str) -> bool:
    torrent_tokens = set(_simple_title_tokens(torrent_name))
    if not torrent_tokens:
        return False
    for title in (anime.get("title"), anime.get("original_title")):
        title_tokens = _simple_title_tokens(str(title or ""))
        if title_tokens and all(token in torrent_tokens for token in title_tokens[:2]):
            return True
    return False


def _simple_title_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in {"the", "a", "an", "season", "s", "tv", "web", "dl", "rip", "x264", "x265", "h264", "h265", "hevc", "avc", "aac", "ddp", "multi", "subs", "dual", "audio"}
        and not token.isdigit()
        and not re.fullmatch(r"s\d{1,2}e\d{1,3}", token)
    ]


def _missing_episode_numbers(anime: dict[str, Any]) -> list[int]:
    completion = anime.get("completion")
    if not isinstance(completion, dict):
        return []
    target = _int_value(completion.get("progress_target")) or _int_value(completion.get("expected_episodes"))
    local_count = _int_value(completion.get("local_episodes")) or 0
    if target is None:
        return []
    if anime.get("library_state") == "Completed" or local_count >= target:
        return []
    local_episode_numbers = _local_episode_numbers(anime)
    if local_episode_numbers:
        return [episode for episode in range(1, target + 1) if episode not in local_episode_numbers]
    return list(range(local_count + 1, target + 1))


def _local_episode_numbers(anime: dict[str, Any]) -> set[int]:
    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list):
        return set()
    expected_episodes = _expected_episode_count(anime)
    return _episode_numbers_from_file_paths(_episode_file_paths_for_selected_season(anime, episode_files), expected_episodes)

def _active_download_queue(anime: dict[str, Any]) -> bool:
    return any(
        queue.get("status") in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged"}
        and not _queue_episode_is_local(anime, queue)
        for queue in _download_queue_items(anime)
    )


def _download_queue_items(anime: dict[str, Any]) -> list[dict[str, Any]]:
    queues: list[dict[str, Any]] = []
    raw_queues = anime.get("download_queues")
    if isinstance(raw_queues, list):
        queues.extend(queue for queue in raw_queues if isinstance(queue, dict))
    legacy_queue = anime.get("download_queue")
    if isinstance(legacy_queue, dict):
        legacy_key = _queue_identity(legacy_queue)
        if not legacy_key or all(_queue_identity(queue) != legacy_key for queue in queues):
            queues.append(legacy_queue)
    return queues


def _sync_primary_download_queue(anime: dict[str, Any], queues: list[dict[str, Any]] | None = None) -> None:
    queue_items = queues if queues is not None else _download_queue_items(anime)
    if len(queue_items) > 1 or isinstance(anime.get("download_queues"), list):
        anime["download_queues"] = queue_items
    active_queue = next((queue for queue in queue_items if queue.get("status") in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged"}), None)
    anime["download_queue"] = active_queue or (queue_items[0] if queue_items else {})


def _queue_identity(queue: dict[str, Any]) -> str:
    for field in ("hash", "infohash"):
        value = str(queue.get(field) or "").strip().casefold()
        if value:
            return f"hash:{value}"
    for field in ("torrent_url", "detail_url", "title"):
        value = str(queue.get(field) or "").strip().casefold()
        if value:
            return f"{field}:{value}"
    return ""


def _active_queue_identity_keys(anime: dict[str, Any]) -> set[str]:
    active_statuses = {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged", "completed", "imported"}
    return {
        key
        for queue in _download_queue_items(anime)
        if queue.get("status") in active_statuses
        for key in [_queue_identity(queue)]
        if key
    }

def _queued_episode_numbers(anime: dict[str, Any]) -> set[int]:
    episodes: set[int] = set()
    for queue in _download_queue_items(anime):
        if queue.get("status") not in {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged", "completed", "imported"}:
            continue
        episode = _int_value(queue.get("episode"))
        if episode is not None:
            episodes.add(episode)
            continue
        wanted = queue.get("wanted_episodes")
        if isinstance(wanted, list) and len(wanted) == 1:
            episode = _int_value(wanted[0])
            if episode is not None:
                episodes.add(episode)
    return episodes


def _append_torrent_notice(anime: dict[str, Any], message: str) -> None:
    torrent_search = anime.setdefault("torrent_search", {})
    notices = torrent_search.setdefault("notices", [])
    if isinstance(notices, list) and message not in notices:
        notices.append(message)


def _find_database_anime(database: dict[str, Any], library_id: str) -> dict[str, Any] | None:
    return next(
        (
            anime
            for anime in database.get("anime", [])
            if isinstance(anime, dict) and str(anime.get("library_id") or "") == library_id
        ),
        None,
    )


def _record_ignored_torrent(database: dict[str, Any], anime: dict[str, Any], torrent: dict[str, Any]) -> None:
    ignored_torrents = database.setdefault("ignored_torrents", [])
    if not isinstance(ignored_torrents, list):
        ignored_torrents = []
        database["ignored_torrents"] = ignored_torrents

    key = _torrent_ignore_key(torrent)
    if not key:
        return
    if any(isinstance(item, dict) and item.get("key") == key for item in ignored_torrents):
        return

    ignored_torrents.append(
        {
            "key": key,
            "title": str(torrent.get("title") or ""),
            "hash": str(torrent.get("hash") or torrent.get("infohash") or "").casefold(),
            "detail_url": str(torrent.get("detail_url") or ""),
            "torrent_url": str(torrent.get("torrent_url") or ""),
            "anime_library_id": str(anime.get("library_id") or ""),
            "anime_title": str(anime.get("title") or anime.get("original_title") or ""),
            "flagged_files": _limited_list(torrent.get("flagged_files"), MAX_FLAGGED_FILES_PER_QUEUE),
            "ignored_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    _prune_ignored_torrents(database)


def _ignored_torrent_keys(database: dict[str, Any]) -> set[str]:
    ignored_torrents = database.get("ignored_torrents")
    keys = {
        str(item.get("key") or "")
        for item in (ignored_torrents if isinstance(ignored_torrents, list) else [])
        if isinstance(item, dict) and str(item.get("key") or "").strip()
    }
    keys.update(_cold_ignored_torrent_keys())
    return keys


def _cold_ignored_torrent_keys() -> set[str]:
    keys: set[str] = set()
    for record in _iter_cold_storage_events(IGNORED_TORRENTS_COLD_STORAGE_PATH) or []:
        if str(record.get("action") or "ignore") != "ignore":
            continue
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        key = str(payload.get("key") or "").strip()
        if key:
            keys.add(key)
    return keys


def _torrent_ignore_key(torrent: dict[str, Any]) -> str:
    for field in ("infohash", "hash"):
        value = str(torrent.get(field) or "").strip().casefold()
        if value:
            return f"hash:{value}"
    for field in ("guid", "detail_url", "torrent_url", "title"):
        value = str(torrent.get(field) or "").strip().casefold()
        if value:
            return f"{field}:{value}"
    return ""


def _safe_folder_name(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]+', " ", value).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:120].rstrip(". ") or "Anime"


def _import_root_folder_anime(database: dict[str, Any], root_folder: Path) -> dict[str, int]:
    _update_root_scan_progress(phase="Reading folders", current=0, total=0, message=f"Reading folders from {root_folder}")
    candidates = _root_folder_candidates(root_folder)
    return _import_root_folder_candidates(database, root_folder, candidates)


def _import_root_folder_candidates(database: dict[str, Any], root_folder: Path, candidates: list[dict[str, Any]]) -> dict[str, int]:
    summary = _empty_scan_summary()
    total = len(candidates)
    _update_root_scan_progress(phase="Importing", current=0, total=total, message=f"Found {total} anime candidate(s) in {root_folder}.")
    for index, candidate in enumerate(candidates, start=1):
        stored_item = _store_root_folder_candidate(database, candidate, summary)
        _update_root_scan_progress(
            phase="Importing",
            current=index,
            total=total,
            summary=summary,
            message=f"Imported {index} of {total}: {stored_item.get('title') or stored_item.get('original_title') or 'Unknown'}",
        )

    return summary


def _import_root_folder_children(database: dict[str, Any], root_folder: Path, children: list[Path]) -> dict[str, int]:
    summary = _empty_scan_summary()
    total = len(children)
    imported_count = 0
    _update_root_scan_progress(phase="Checking media", current=0, total=total, message=f"Checking {total} top-level item(s) for anime media.")
    for index, child in enumerate(children, start=1):
        _update_root_scan_progress(phase="Checking media", current=index, total=total, summary=summary, message=f"Checking {index} of {total}: {child.name}")
        candidate = _root_folder_candidate_from_child(child)
        if candidate is None:
            summary["skipped"] += 1
            continue
        imported_count += 1
        _update_root_scan_progress(phase="Resolving metadata", current=index, total=total, summary=summary, message=f"Resolving metadata for {child.name}")
        stored_item = _store_root_folder_candidate(database, candidate, summary)
        _update_root_scan_progress(
            phase="Importing",
            current=index,
            total=total,
            summary=summary,
            message=f"Imported {imported_count}: {stored_item.get('title') or stored_item.get('original_title') or 'Unknown'}",
        )
    return summary


def _append_cold_storage_event(path: Path, action: str, payload: dict[str, Any]) -> None:
    record = {"action": action, "payload": payload, "recorded_at": datetime.now(timezone.utc).isoformat()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as cold_file:
            cold_file.write(json.dumps(record, sort_keys=True) + "\n")
    except OSError:
        return

def _iter_cold_storage_events(path: Path) -> Any:
    try:
        cold_file = path.open("r", encoding="utf-8")
    except OSError:
        return
    with cold_file:
        for line in cold_file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                yield record


def _monitoring_title_keys(anime: dict[str, Any]) -> set[str]:
    values = [anime.get("title"), anime.get("original_title")]
    aliases = anime.get("aliases")
    if isinstance(aliases, list):
        values.extend(aliases)
    return {_metadata_compare_value(value) for value in values if _metadata_compare_value(value)}


def _monitoring_provider_ids(anime: dict[str, Any]) -> dict[str, str]:
    provider_ids = anime.get("provider_ids") if isinstance(anime.get("provider_ids"), dict) else {}
    return {str(provider): str(value).strip() for provider, value in provider_ids.items() if str(value or "").strip()}


def _unmonitored_entry_matches_anime(entry: dict[str, Any], anime: dict[str, Any]) -> bool:
    entry_ids = entry.get("provider_ids") if isinstance(entry.get("provider_ids"), dict) else {}
    anime_ids = _monitoring_provider_ids(anime)
    for provider, value in entry_ids.items():
        if str(value or "").strip() and anime_ids.get(str(provider)) == str(value).strip():
            return True
    title_key = str(entry.get("title_key") or "").strip()
    return bool(title_key and title_key in _monitoring_title_keys(anime))


def _unmonitored_library_title_match(database: dict[str, Any], anime: dict[str, Any]) -> bool:
    for existing in database.get("anime", []):
        if not isinstance(existing, dict) or existing.get("monitored") is not False:
            continue
        if str(existing.get("library_id") or "") == str(anime.get("library_id") or ""):
            return True
        if _unmonitored_entry_matches_anime(_unmonitored_title_entry(existing), anime):
            return True
    return False


def _unmonitored_title_entry(anime: dict[str, Any]) -> dict[str, Any]:
    title = str(anime.get("title") or anime.get("original_title") or "").strip()
    keys = _monitoring_title_keys(anime)
    return {
        "title": title,
        "title_key": _metadata_compare_value(title) or (sorted(keys)[0] if keys else ""),
        "provider_ids": _monitoring_provider_ids(anime),
        "library_id": str(anime.get("library_id") or "").strip(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


def _title_is_unmonitored(database: dict[str, Any], anime: dict[str, Any]) -> bool:
    entries = database.get("unmonitored_titles") if isinstance(database.get("unmonitored_titles"), list) else []
    if any(isinstance(entry, dict) and _unmonitored_entry_matches_anime(entry, anime) for entry in entries):
        return True
    if _unmonitored_library_title_match(database, anime):
        return True
    cold_match = _cold_unmonitored_title_match(anime)
    return bool(cold_match) if cold_match is not None else False


def _remember_unmonitored_title(database: dict[str, Any], anime: dict[str, Any]) -> None:
    entries = database.setdefault("unmonitored_titles", [])
    if not isinstance(entries, list):
        entries = []
        database["unmonitored_titles"] = entries
    entry = _unmonitored_title_entry(anime)
    entries[:] = [existing for existing in entries if not (isinstance(existing, dict) and _unmonitored_entry_matches_anime(existing, anime))]
    entries.append(entry)


def _forget_unmonitored_title(database: dict[str, Any], anime: dict[str, Any]) -> None:
    entries = database.get("unmonitored_titles")
    removed_hot = False
    if isinstance(entries, list):
        kept = [entry for entry in entries if not (isinstance(entry, dict) and _unmonitored_entry_matches_anime(entry, anime))]
        removed_hot = len(kept) != len(entries)
        database["unmonitored_titles"] = kept
    if removed_hot or _cold_unmonitored_title_match(anime) is True:
        _append_unmonitored_title_cold_event("unpause", _unmonitored_title_entry(anime))


def _append_unmonitored_title_cold_event(action: str, entry: dict[str, Any]) -> None:
    normalized = _normalized_unmonitored_title_entry(entry)
    if normalized is None:
        return
    _append_cold_storage_event(UNMONITORED_TITLES_COLD_STORAGE_PATH, action, normalized)

def _archive_unmonitored_title_entries(entries: list[dict[str, Any]]) -> None:
    for entry in entries:
        _append_unmonitored_title_cold_event("pause", entry)


def _cold_unmonitored_title_match(anime: dict[str, Any]) -> bool | None:
    try:
        cold_file = UNMONITORED_TITLES_COLD_STORAGE_PATH.open("r", encoding="utf-8")
    except OSError:
        return None
    matched: bool | None = None
    with cold_file:
        for line in cold_file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            payload = record.get("payload") if isinstance(record.get("payload"), dict) else record.get("entry")
            entry = payload if isinstance(payload, dict) else {}
            if not _unmonitored_entry_matches_anime(entry, anime):
                continue
            matched = str(record.get("action") or "pause") == "pause"
    return matched


def _normalized_unmonitored_title_entry(entry: dict[str, Any]) -> dict[str, Any] | None:
    title_key = str(entry.get("title_key") or "").strip()
    provider_ids = entry.get("provider_ids") if isinstance(entry.get("provider_ids"), dict) else {}
    normalized_ids = {str(provider): str(value).strip() for provider, value in provider_ids.items() if str(value or "").strip()}
    if not title_key and not normalized_ids:
        return None
    return {
        "title": str(entry.get("title") or "").strip(),
        "title_key": title_key,
        "provider_ids": normalized_ids,
        "library_id": str(entry.get("library_id") or "").strip(),
        "recorded_at": str(entry.get("recorded_at") or "").strip(),
    }


def _unmonitored_entry_identity(entry: dict[str, Any]) -> tuple[str, str]:
    provider_ids = entry.get("provider_ids") if isinstance(entry.get("provider_ids"), dict) else {}
    return (
        str(entry.get("title_key") or "").strip(),
        "|".join(f"{provider}:{value}" for provider, value in sorted(provider_ids.items())),
    )


def _apply_unmonitored_title_guard(database: dict[str, Any], anime: dict[str, Any]) -> bool:
    if not _title_is_unmonitored(database, anime):
        return False
    anime["monitored"] = False
    _clear_download_plan_for_unmonitored(anime)
    _refresh_library_state(anime, root_folder_configured=_root_folder_configured(database))
    return True


def _store_root_folder_candidate(database: dict[str, Any], candidate: dict[str, Any], summary: dict[str, int]) -> dict[str, Any]:
    existing = next((item for item in database["anime"] if item["library_id"] == candidate["library_id"]), None)
    merge_target = _find_existing_root_import_target(database["anime"], candidate)
    if merge_target is not None:
        if existing is not None and existing is not merge_target:
            database["anime"].remove(existing)
        existing = merge_target
    duplicate_title = None
    if existing is None:
        duplicate_title = _find_duplicate_title_conflict(database["anime"], candidate, exclude_library_id=str(candidate.get("library_id") or ""))
    if duplicate_title is not None:
        _resolve_duplicate_title_conflict(candidate, duplicate_title)
    if existing is None:
        _apply_unmonitored_title_guard(database, candidate)
        database["anime"].append(candidate)
        stored_item = candidate
        summary["imported"] += 1
    else:
        _update_imported_anime(existing, candidate)
        _apply_unmonitored_title_guard(database, existing)
        stored_item = existing
        summary["updated"] += 1

    if stored_item.get("manual_verification_required"):
        summary["manual_verification"] += 1
    else:
        summary["verified"] += 1
        _sync_anime_nfo_file(stored_item)
    _mark_torrent_search_pending(stored_item)
    return stored_item


def _root_folder_candidates(root_folder: Path) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    children = _root_folder_children(root_folder)
    total = len(children)
    _update_root_scan_progress(phase="Checking media", current=0, total=total, message=f"Checking {total} top-level item(s) for anime media.")
    for index, child in enumerate(children, start=1):
        _update_root_scan_progress(phase="Checking media", current=index, total=total, message=f"Checking {index} of {total}: {child.name}")
        candidate = _root_folder_candidate_from_child(child)
        if candidate is None:
            continue
        _update_root_scan_progress(phase="Resolving metadata", current=index, total=total, message=f"Resolving metadata for {child.name}")
        candidates.append(candidate)

    _update_root_scan_progress(phase="Importing", current=0, total=len(candidates), message=f"Found {len(candidates)} anime candidate(s).")
    return candidates


def _root_folder_children(root_folder: Path) -> list[Path]:
    return sorted(root_folder.iterdir(), key=lambda path: path.name.casefold())


def _root_folder_candidate_from_child(child: Path) -> dict[str, Any] | None:
    if child.is_dir():
        media_files = _media_files(child)
        if not media_files:
            return None
        return _imported_anime_item(child.name, child, media_files)
    if child.is_file() and child.suffix.casefold() in MEDIA_EXTENSIONS:
        return _imported_anime_item(_title_from_media_file(child), child, [child])
    return None


def _imported_anime_item(
    title: str,
    source_path: Path,
    media_files: list[Path],
    *,
    nfo_path: Path | None = None,
) -> dict[str, Any]:
    resolved_path = source_path.resolve()
    if nfo_path is None:
        nfo_path = source_path / "tvshow.nfo" if source_path.is_dir() else source_path.with_suffix(".nfo")
    nfo_metadata = _read_anime_nfo(nfo_path)
    normalized_title = _clean_import_title(str(nfo_metadata.get("title") or title))
    base_item = {
        "library_id": f"root-folder:{_stable_path_id(resolved_path)}",
        "title": normalized_title,
        "original_title": normalized_title,
        "year": "Unknown",
        "status": "Unknown",
        "episodes": str(len(media_files)),
        "season_number": 1,
        "runtime": "Unknown",
        "genres": [],
        "studio": "Unknown",
        "source": "Root Folder Scan",
        "rating": "Unrated",
        "synopsis": "Imported from the configured root folder.",
        "poster": "",
        "air_date": "",
        "next_airing_at": "",
        "airing_episode": "",
        "airing_source": "",
        "monitored": True,
        "library_state": "Monitored",
        "quality_resolution": "1080p",
        "quality_profile": "Up to: 1080p",
        "local_path": str(resolved_path),
        "episode_files": [str(path.resolve()) for path in media_files],
        "torrent_search": {
            "query": normalized_title,
            "strategy": "Imported from root folder scan",
            "candidates": [],
            "notices": ["Already present in the configured root folder."],
        },
    }
    _apply_nfo_metadata(base_item, nfo_metadata)
    resolved_item = _resolve_imported_anime_metadata_from_nfo(base_item, normalized_title, nfo_metadata)
    if resolved_item is None:
        resolved_item = _resolve_imported_anime_metadata(base_item, normalized_title)
    _refresh_media_tag(resolved_item)
    _refresh_library_state(resolved_item)
    return resolved_item


def _read_anime_nfo(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        root = ET.fromstring(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, ET.ParseError):
        return {}
    if root.tag.casefold().rsplit("}", 1)[-1] != "tvshow":
        return {}

    def text(name: str) -> str:
        element = root.find(name)
        return str(element.text or "").strip() if element is not None else ""

    provider_ids: dict[str, str] = {}
    unique_ids = list(root.findall("uniqueid"))
    unique_ids.sort(key=lambda element: str(element.attrib.get("default") or "").casefold() != "true")
    for element in unique_ids:
        provider = str(element.attrib.get("type") or "").strip().casefold()
        value = str(element.text or "").strip()
        if provider and value and provider not in provider_ids:
            provider_ids[provider] = value
    legacy_id = text("id")
    if ":" in legacy_id:
        provider, value = legacy_id.split(":", 1)
        if provider.strip() and value.strip():
            provider_ids.setdefault(provider.strip().casefold(), value.strip())
    genres = [str(element.text or "").strip() for element in root.findall("genre")]
    genres = [genre for genre in genres if genre]
    thumb = next((str(element.text or "").strip() for element in root.findall("thumb") if str(element.text or "").strip()), "")
    return {
        "title": text("title"), "original_title": text("originaltitle"), "provider_ids": provider_ids,
        "synopsis": text("plot"), "air_date": text("premiered"), "year": text("year"),
        "status": text("status"), "studio": text("studio"), "genres": genres, "poster": thumb,
    }


def _apply_nfo_metadata(item: dict[str, Any], metadata: dict[str, Any]) -> None:
    if not metadata:
        return
    for source, target in {
        "title": "title", "original_title": "original_title", "synopsis": "synopsis",
        "air_date": "air_date", "year": "year", "status": "status", "studio": "studio", "poster": "poster",
    }.items():
        value = metadata.get(source)
        if str(value or "").strip():
            item[target] = value
    if metadata.get("genres"):
        item["genres"] = list(metadata["genres"])
    if metadata.get("provider_ids"):
        item["provider_ids"] = dict(metadata["provider_ids"])
    item["source"] = "Root Folder Scan + NFO"
    item["nfo_metadata"] = True


def _resolve_imported_anime_metadata_from_nfo(
    item: dict[str, Any], import_title: str, metadata: dict[str, Any]
) -> dict[str, Any] | None:
    provider_ids = metadata.get("provider_ids") if isinstance(metadata.get("provider_ids"), dict) else {}
    anilist_id = str(provider_ids.get("anilist") or "").strip()
    if not anilist_id:
        return None
    search_titles = _metadata_match_context(import_title)["search_titles"]
    try:
        match = search_anilist_by_id(anilist_id)
    except MetadataProviderError as exc:
        item["anilist_reconciliation_status"] = "pending"
        item["anilist_reconciliation_reason"] = str(exc)
        item["manual_verification_required"] = False
        item["metadata_search_titles"] = search_titles
        return item
    if not isinstance(match, dict) or not match:
        item["manual_verification_required"] = True
        item["manual_verification_reason"] = f"The NFO AniList ID {anilist_id} could not be resolved."
        item["metadata_search_titles"] = search_titles
        return item
    context = _metadata_match_context(
        import_title,
        local_episode_count=_local_episode_count(item),
        local_season_number=_local_episode_file_season_hint(item),
    )
    if not _metadata_episode_count_compatible(context, match):
        item["manual_verification_required"] = True
        item["manual_verification_reason"] = (
            f"The folder contains {_local_episode_count(item)} media files, which conflicts with "
            f"AniList ID {anilist_id}. Check this folder for files belonging to other anime."
        )
        item["metadata_candidates"] = _metadata_candidate_preview([match])
        item["metadata_search_titles"] = search_titles
        return item
    return _apply_resolved_metadata(item, match, search_titles, "provider")

def _refresh_library_states(library: list[dict[str, Any]], *, root_folder_configured: bool | None = None) -> dict[str, int]:

    summary = {"completed": 0, "monitored": 0, "paused": 0, "undownloadable": 0, "unknown": 0}
    for anime in library:
        state = _refresh_library_state(anime, root_folder_configured=root_folder_configured)
        key = state.casefold()
        if key in summary:
            summary[key] += 1
        else:
            summary["unknown"] += 1
    return summary


def _refresh_library_state(anime: dict[str, Any], *, root_folder_configured: bool | None = None) -> str:
    provider_expected_episodes = _expected_episode_count(anime)
    expected_episodes = _adjusted_expected_episode_count(anime, provider_expected_episodes)
    local_episode_count = _local_episode_count(anime)
    progress_target = _progress_episode_target(anime, expected_episodes)
    anime["completion"] = _completion_payload(anime, local_episode_count, expected_episodes, progress_target)
    if _is_finished_status(anime.get("status")) and expected_episodes is not None and local_episode_count >= expected_episodes:
        anime["library_state"] = "Completed"
        anime["completion"] = _completion_payload(anime, local_episode_count, expected_episodes, progress_target)
        _refresh_airing_state(anime)
        _refresh_progress_tone(anime)
        return "Completed"

    if root_folder_configured is False and anime.get("monitored") and _needs_download_target(anime):
        anime["library_state"] = "Undownloadable"
        anime["undownloadable_reason"] = "No root folder selected, Nyaarr is unable to find a folder to place this anime into"
    elif anime.get("monitored"):
        anime["library_state"] = "Monitored"
        anime.pop("undownloadable_reason", None)
    else:
        anime["library_state"] = "Paused"
        anime.pop("undownloadable_reason", None)
    _refresh_airing_state(anime)
    _refresh_progress_tone(anime)
    return anime["library_state"]


def _root_folder_configured(database: dict[str, Any]) -> bool:
    return bool(str(database.get("settings", {}).get("root_folder") or "").strip())


def _needs_download_target(anime: dict[str, Any]) -> bool:
    completion = anime.get("completion")
    if isinstance(completion, dict):
        return int(completion.get("missing_episodes") or 0) > 0
    expected_episodes = _adjusted_expected_episode_count(anime, _expected_episode_count(anime))
    return expected_episodes is None or _local_episode_count(anime) < expected_episodes


def _expected_episode_count(anime: dict[str, Any]) -> int | None:
    value = anime.get("episodes")
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    match = re.search(r"\d+", value)
    if not match:
        return None
    count = int(match.group(0))
    return count if count > 0 else None


def _adjusted_expected_episode_count(anime: dict[str, Any], expected_episodes: int | None) -> int | None:
    if expected_episodes is None:
        anime.pop("episode_count_adjustment", None)
        return None

    local_episode_numbers = _local_episode_numbers(anime)
    if not local_episode_numbers:
        anime.pop("episode_count_adjustment", None)
        return expected_episodes

    max_local_episode = max(local_episode_numbers)
    special_count = _local_special_episode_file_count(anime)
    has_complete_main_run = len(local_episode_numbers) == max_local_episode
    provider_total_explained_by_specials = max_local_episode < expected_episodes <= max_local_episode + special_count
    if special_count > 0 and has_complete_main_run and provider_total_explained_by_specials:
        anime["episode_count_adjustment"] = {
            "provider_expected_episodes": expected_episodes,
            "main_expected_episodes": max_local_episode,
            "local_special_files": special_count,
            "reason": "Provider episode count appears to include local recap or special files.",
        }
        return max_local_episode

    anime.pop("episode_count_adjustment", None)
    return expected_episodes


def _int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value >= 0 else None
    match = re.search(r"\d+", str(value or ""))
    if not match:
        return None
    return int(match.group(0))


def _local_episode_count(anime: dict[str, Any]) -> int:
    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list):
        return 0
    paths = _episode_file_paths_for_selected_season(anime, episode_files)
    expected_episodes = _expected_episode_count(anime)
    parsed_episodes = _episode_numbers_from_file_paths(paths, expected_episodes)
    if parsed_episodes:
        return len(parsed_episodes)
    return len(paths)


def _episode_numbers_from_file_paths(paths: list[str], expected_episodes: int | None = None) -> set[int]:
    episode_numbers: set[int] = set()
    for path in paths:
        episode = episode_number_from_title(Path(str(path or "")).name)
        if episode is None or episode <= 0:
            continue
        if expected_episodes is not None and episode > expected_episodes:
            continue
        episode_numbers.add(episode)
    return episode_numbers


def _local_special_episode_file_count(anime: dict[str, Any]) -> int:
    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list):
        return 0
    paths = _episode_file_paths_for_selected_season(anime, episode_files)
    return sum(1 for path in paths if _looks_like_special_episode_file(Path(str(path or "")).name))


def _looks_like_special_episode_file(filename: str) -> bool:
    if re.search(r"\bS\d{1,2}E0{1,3}(?=\b|v\d|\.|$)", filename, flags=re.IGNORECASE):
        return True
    if re.search(r"\bS\d{1,2}E\d{1,3}\.\d+", filename, flags=re.IGNORECASE):
        return True
    if re.search(r"(?:^|\s)-\s*\d{1,3}\.\d+(?=\s|v\d|\[|\(|\.|$)", filename, flags=re.IGNORECASE):
        return True
    return False


def _episode_file_paths_for_selected_season(anime: dict[str, Any], files: list[Any]) -> list[str]:
    paths = [str(value or "") for value in files if str(value or "").strip()]
    season_paths = _paths_inside_selected_season_folder(anime, paths)
    return season_paths if season_paths else paths


def _paths_inside_selected_season_folder(anime: dict[str, Any], paths: list[str]) -> list[str]:
    season = max(_int_value(anime.get("season_number")) or 1, 1)
    selected = [path for path in paths if _path_has_season_folder(path, season)]
    return selected if selected else []


def _path_has_season_folder(path: str, season: int) -> bool:
    labels = {f"season {season}", f"season {season:02d}", f"s{season}", f"s{season:02d}"}
    for part in Path(path).parts[:-1]:
        normalized = re.sub(r"[^a-z0-9]+", " ", part.casefold()).strip()
        compact = re.sub(r"[^a-z0-9]+", "", part.casefold())
        if normalized in labels or compact in {label.replace(" ", "") for label in labels}:
            return True
    return False


def _media_files_for_anime_folder(anime: dict[str, Any], folder: Path) -> list[Path]:
    media_files = _media_files(folder)
    season_files = _paths_inside_selected_season_folder(anime, [str(path) for path in media_files])
    if season_files:
        season_set = {str(Path(path).resolve()) for path in season_files}
        return [path for path in media_files if str(path.resolve()) in season_set]
    return media_files


def _attach_existing_root_episode_files(database: dict[str, Any], anime: dict[str, Any]) -> bool:
    existing_path = str(anime.get("local_path") or "").strip()
    if existing_path and Path(existing_path).exists():
        return False
    root_folder = Path(str(database.get("settings", {}).get("root_folder") or "").strip())
    if not root_folder.exists() or not root_folder.is_dir():
        return False

    candidate_titles = [
        str(anime.get("title") or ""),
        str(anime.get("original_title") or ""),
    ]
    normalized_titles = {re.sub(r"[^a-z0-9]+", "", title.casefold()) for title in candidate_titles if title.strip()}
    if not normalized_titles:
        return False

    children = [child for child in root_folder.iterdir() if child.is_dir()]
    exact_matches = [
        child
        for child in children
        if re.sub(r"[^a-z0-9]+", "", child.name.casefold()) in normalized_titles
    ]
    matches = exact_matches
    if not matches:
        matches = [
            child
            for child in children
            if any(torrent_title_matches(title, child.name) for title in candidate_titles if title.strip())
        ]
    matches_with_media = [(child, _media_files(child)) for child in matches]
    matches_with_media = [(child, files) for child, files in matches_with_media if files]
    if len(matches_with_media) != 1:
        return False

    child, media_files = matches_with_media[0]
    anime["local_path"] = str(child.resolve())
    anime["episode_files"] = [str(path.resolve()) for path in media_files]
    _refresh_media_tag(anime)
    return True


def _completion_payload(
    anime: dict[str, Any],
    local_episode_count: int,
    expected_episodes: int | None,
    progress_target: int | None,
) -> dict[str, Any]:
    if progress_target is None or progress_target <= 0:
        progress_percent = 0
    else:
        progress_percent = round(min(local_episode_count, progress_target) / progress_target * 100)
    return {
        "expected_episodes": expected_episodes,
        "local_episodes": local_episode_count,
        "progress_target": progress_target,
        "missing_episodes": max((progress_target or 0) - local_episode_count, 0),
        "progress_percent": progress_percent,
    }


def _progress_episode_target(anime: dict[str, Any], expected_episodes: int | None) -> int | None:
    state = _airing_state(anime)
    if state == "Not Yet Aired":
        return 0
    if state == "Airing":
        current_episode = _current_aired_episode(anime)
        if current_episode is not None:
            return min(expected_episodes, current_episode) if expected_episodes else current_episode
        if expected_episodes:
            return expected_episodes
    return expected_episodes


def _current_aired_episode(anime: dict[str, Any]) -> int | None:
    aired_episode = _int_value(anime.get("aired_episode"))
    if aired_episode is not None:
        return aired_episode
    next_episode = _int_value(anime.get("airing_episode"))
    if next_episode is not None:
        return max(next_episode - 1, 0)
    return None


def _refresh_progress_tone(anime: dict[str, Any]) -> None:
    state = str(anime.get("library_state") or "")
    if state != "Undownloadable":
        state = str(anime.get("airing_tag") or anime.get("library_state") or "")
    tone = {
        "Completed": "green",
        "Airing": "blue",
        "Not Yet Aired": "yellow",
        "Undownloadable": "orange",
    }.get(state, "blue")
    completion = anime.setdefault("completion", {})
    completion["progress_tone"] = tone
    if state in {"Not Yet Aired", "Undownloadable"}:
        completion["progress_percent"] = 100


def _is_finished_status(status: Any) -> bool:
    return _normalized_status(status) in {"finished", "completed", "ended"}


def _refresh_airing_state(anime: dict[str, Any]) -> str:
    state = _airing_state(anime)
    anime["airing_state"] = state
    anime["airing_tag"] = state
    anime["airing_tag_class"] = _airing_tag_class(state)
    return state


def _airing_state(anime: dict[str, Any]) -> str:
    status = _normalized_status(anime.get("status"))
    if status in {"finished", "completed", "ended"}:
        return "Completed"
    if _current_aired_episode(anime) is not None and _current_aired_episode(anime) > 0:
        return "Airing"
    if status in {"releasing", "airing", "currently airing", "ongoing", "current"}:
        return "Airing"
    if status in {"not yet released", "not yet aired", "upcoming"}:
        return "Not Yet Aired"
    if _anime_air_date(anime) is not None:
        return "Airing"
    return "Unknown"


def _airing_tag_class(state: str) -> str:
    if state == "Airing":
        return "badge-airing"
    if state == "Completed":
        return "badge-ok"
    if state == "Not Yet Aired":
        return "badge-upcoming"
    return "badge-muted"


def _normalized_status(status: Any) -> str:
    return re.sub(r"[_\s-]+", " ", str(status or "").strip().casefold())


def _resolve_imported_anime_metadata(item: dict[str, Any], import_title: str) -> dict[str, Any]:
    match_context = _metadata_match_context(
        import_title,
        local_episode_count=_local_episode_count(item),
        local_season_number=_local_episode_file_season_hint(item),
    )
    search_titles = match_context["search_titles"]
    cached_match = _resolved_metadata_cache_lookup(match_context)
    if cached_match is not None:
        return _apply_resolved_metadata(item, cached_match, search_titles, "cache")
    try:
        results = _search_metadata_variants(search_titles)
    except MetadataProviderError as exc:
        item["manual_verification_required"] = True
        item["manual_verification_reason"] = str(exc)
        item["metadata_candidates"] = []
        item["metadata_search_titles"] = search_titles
        return item

    match = _best_metadata_match(match_context, results)
    item["metadata_candidates"] = _metadata_candidate_preview(results)
    item["metadata_search_titles"] = search_titles
    if match is not None:
        match = _enrich_metadata_poster_from_candidates(match_context, match, results)
    if match is None:
        item["manual_verification_required"] = True
        item["manual_verification_reason"] = "No confident metadata match was found for the folder name."
        return item

    _resolved_metadata_cache_store(match_context, match)
    return _apply_resolved_metadata(item, match, search_titles, "provider")


def _apply_resolved_metadata(
    item: dict[str, Any],
    match: dict[str, Any],
    search_titles: list[str],
    resolution_source: str,
) -> dict[str, Any]:
    existing_poster = str(item.get("poster") or "").strip()
    match_poster = str(match.get("poster") or "").strip()
    poster = match_poster or existing_poster
    poster_source = match.get("poster_source", _metadata_source_name(match)) if match_poster else str(item.get("poster_source") or "")
    source_name = _metadata_source_name(match)
    resolved_title = _resolved_metadata_title(item, match)
    resolved_source = source_name if resolution_source in {"anilist-routine", "manual-anilist-id"} else f"Root Folder Scan + {source_name}"
    item.update(
        {
            "title": resolved_title,
            "original_title": match["original_title"],
            "year": match["year"],
            "status": match["status"],
            "episodes": match.get("episodes", item.get("episodes", "Unknown")),
            "season_number": match["season_number"],
            "runtime": match["runtime"],
            "genres": match["genres"],
            "aliases": match.get("aliases", []),
            "provider_title": match.get("provider_title", item.get("provider_title", {})),
            "studio": match["studio"],
            "source": resolved_source,
            "rating": match["rating"],
            "synopsis": match["synopsis"],
            "poster": poster,
            "poster_source": poster_source,
            "air_date": match.get("air_date", ""),
            "next_airing_at": match.get("next_airing_at", ""),
            "airing_episode": match.get("airing_episode", ""),
            "airing_source": match.get("airing_source", ""),
            "media_format": match.get("media_format", item.get("media_format", "")),
            "release_season": match.get("release_season", item.get("release_season", "")),
            "season_year": match.get("season_year", item.get("season_year", "")),
            "start_date": match.get("start_date", item.get("start_date", "")),
            "end_date": match.get("end_date", item.get("end_date", "")),
            "source_material": match.get("source_material", item.get("source_material", "")),
            "country_of_origin": match.get("country_of_origin", item.get("country_of_origin", "")),
            "is_adult": bool(match.get("is_adult", item.get("is_adult", False))),
            "anilist_updated_at": match.get("anilist_updated_at", item.get("anilist_updated_at", "")),
            "provider_ids": match.get("provider_ids", {}),
            "manual_verification_required": False,
            "manual_verification_reason": "",
            "metadata_candidates": [],
            "metadata_resolution_source": resolution_source,
            "metadata_search_titles": search_titles,
        }
    )
    item["torrent_search"]["query"] = resolved_title
    if resolution_source == "provider":
        item["torrent_search"]["notices"] = [f"Imported from root folder and matched to {match['source']} metadata."]
    _mark_anilist_reconciliation_for_match(item, match)
    return item


def _resolved_metadata_title(item: dict[str, Any], match: dict[str, Any]) -> str:
    match_title = str(match.get("title") or "").strip()
    existing_title = str(item.get("title") or "").strip()
    if not existing_title or _metadata_source_name(match) != "AniList":
        return match_title
    if _metadata_compare_value(existing_title) == _metadata_compare_value(match_title):
        return match_title
    if _metadata_title_in_values(existing_title, _metadata_confidence_title_values(match)):
        return existing_title
    return match_title


def _metadata_title_in_values(title: str, values: list[tuple[Any, float]]) -> bool:
    title_key = _metadata_compare_value(title)
    return bool(title_key) and any(_metadata_compare_value(value) == title_key for value, _weight in values)


def _find_duplicate_title_conflict(
    library: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    exclude_library_id: str = "",
) -> dict[str, Any] | None:
    candidate_title_key = _duplicate_title_key(candidate)
    if not candidate_title_key:
        return None
    for existing in library:
        if not isinstance(existing, dict):
            continue
        if exclude_library_id and str(existing.get("library_id") or "") == exclude_library_id:
            continue
        if _duplicate_title_key(existing) != candidate_title_key:
            continue
        if not _anime_content_identical(existing, candidate):
            return existing
    return None


def _find_existing_root_import_target(library: list[dict[str, Any]], candidate: dict[str, Any]) -> dict[str, Any] | None:
    for existing in library:
        if not isinstance(existing, dict):
            continue
        if str(existing.get("library_id") or "") == str(candidate.get("library_id") or ""):
            continue
        if _same_local_path(existing, candidate):
            return existing
        if _anime_content_matches_partial_import(existing, candidate):
            return existing
    return None


def _same_local_path(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_path = str(left.get("local_path") or "").strip().casefold()
    right_path = str(right.get("local_path") or "").strip().casefold()
    return bool(left_path and right_path and left_path == right_path)


def _anime_content_matches_partial_import(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if _duplicate_title_key(existing) != _duplicate_title_key(candidate):
        return False
    expected_count = _expected_episode_count(existing) or _expected_episode_count(candidate)
    local_count = _local_episode_count(candidate)
    if expected_count is None or local_count <= 0 or local_count > expected_count:
        return False
    existing_provider_ids = existing.get("provider_ids") if isinstance(existing.get("provider_ids"), dict) else {}
    candidate_provider_ids = candidate.get("provider_ids") if isinstance(candidate.get("provider_ids"), dict) else {}
    return any(
        existing_provider_ids.get(provider) not in (None, "")
        and existing_provider_ids.get(provider) == candidate_provider_ids.get(provider)
        for provider in set(existing_provider_ids) | set(candidate_provider_ids)
    )

def _duplicate_title_key(anime: dict[str, Any]) -> str:
    return _metadata_compare_value(anime.get("title") or anime.get("original_title") or "")


def _anime_content_identical(left: dict[str, Any], right: dict[str, Any]) -> bool:
    left_expected = _expected_episode_count(left)
    right_expected = _expected_episode_count(right)
    left_local = _local_episode_count(left)
    right_local = _local_episode_count(right)
    left_provider_ids = left.get("provider_ids") if isinstance(left.get("provider_ids"), dict) else {}
    right_provider_ids = right.get("provider_ids") if isinstance(right.get("provider_ids"), dict) else {}
    shared_provider = any(
        left_provider_ids.get(provider) not in (None, "") and left_provider_ids.get(provider) == right_provider_ids.get(provider)
        for provider in set(left_provider_ids) | set(right_provider_ids)
    )
    same_expected = left_expected is not None and right_expected is not None and left_expected == right_expected
    same_local = left_local > 0 and left_local == right_local
    return shared_provider and same_expected and same_local


def _resolve_duplicate_title_conflict(candidate: dict[str, Any], existing: dict[str, Any]) -> None:
    candidate_season_match = _local_import_matches_metadata_season(candidate)
    existing_season_match = _local_import_matches_metadata_season(existing)
    if candidate_season_match and not existing_season_match:
        _mark_duplicate_title_conflict(existing, candidate)
    elif existing_season_match and not candidate_season_match:
        _mark_duplicate_title_conflict(candidate, existing)
    elif _episode_count_overflows_metadata(existing) and not _episode_count_overflows_metadata(candidate):
        _mark_duplicate_title_conflict(existing, candidate)
    else:
        _mark_duplicate_title_conflict(candidate, existing)


def _episode_count_overflows_metadata(anime: dict[str, Any]) -> bool:
    local_count = _local_episode_count(anime)
    expected_count = _expected_episode_count(anime)
    return local_count > 0 and expected_count is not None and local_count > expected_count


def _local_import_matches_metadata_season(anime: dict[str, Any]) -> bool:
    metadata_season = _season_hint_value(anime.get("season_number"))
    local_season = _season_hint_from_title(_local_title_from_import(anime))
    return metadata_season is not None and local_season is not None and metadata_season == local_season


def _mark_duplicate_title_conflict(candidate: dict[str, Any], existing: dict[str, Any]) -> None:
    resolved_title = str(candidate.get("title") or candidate.get("original_title") or "Unknown anime")
    local_title = _local_title_from_import(candidate) or resolved_title
    if _metadata_compare_value(local_title) == _metadata_compare_value(resolved_title):
        local_episode_count = _local_episode_count(candidate)
        local_title = f"{local_title} ({local_episode_count} local episodes)" if local_episode_count else f"{local_title} (local import)"
    candidate["title"] = local_title
    candidate["manual_verification_required"] = True
    candidate["manual_verification_reason"] = (
        f"Duplicate metadata title '{resolved_title}' conflicts with an existing library item. "
        "The detected episode counts differ, so this import needs manual metadata verification."
    )
    candidate["duplicate_title_conflict"] = {
        "resolved_title": resolved_title,
        "existing_library_id": str(existing.get("library_id") or ""),
        "existing_local_episodes": _local_episode_count(existing),
        "candidate_local_episodes": _local_episode_count(candidate),
        "existing_expected_episodes": _expected_episode_count(existing),
        "candidate_expected_episodes": _expected_episode_count(candidate),
    }
    torrent_search = candidate.setdefault("torrent_search", {})
    if isinstance(torrent_search, dict):
        torrent_search["query"] = local_title
        torrent_search["strategy"] = "Manual metadata verification required"
        torrent_search["candidates"] = []
        torrent_search["notices"] = [candidate["manual_verification_reason"]]


def _local_title_from_import(anime: dict[str, Any]) -> str:
    local_path = str(anime.get("local_path") or "").strip()
    if local_path:
        return _clean_import_title(Path(local_path).name)
    search_titles = anime.get("metadata_search_titles")
    if isinstance(search_titles, list) and search_titles:
        return str(search_titles[0] or "").strip()
    return ""


def _merge_same_path_root_folder_duplicates(library: list[dict[str, Any]]) -> bool:
    canonical_by_path: dict[str, dict[str, Any]] = {}
    for anime in library:
        if not isinstance(anime, dict) or _is_root_folder_import(anime):
            continue
        local_path = _normalized_local_path(anime)
        if local_path and local_path not in canonical_by_path:
            canonical_by_path[local_path] = anime

    changed = False
    for anime in list(library):
        if not isinstance(anime, dict) or not _is_root_folder_import(anime):
            continue
        local_path = _normalized_local_path(anime)
        canonical = canonical_by_path.get(local_path)
        if canonical is None:
            continue
        _merge_root_folder_duplicate_into_existing(canonical, anime)
        library.remove(anime)
        changed = True
    return changed


def _is_root_folder_import(anime: dict[str, Any]) -> bool:
    return str(anime.get("library_id") or "").startswith("root-folder:")


def _normalized_local_path(anime: dict[str, Any]) -> str:
    return str(anime.get("local_path") or "").strip().replace("/", "\\").casefold()


def _merge_root_folder_duplicate_into_existing(existing: dict[str, Any], duplicate: dict[str, Any]) -> None:
    if duplicate.get("local_path"):
        existing["local_path"] = duplicate["local_path"]
    duplicate_files = duplicate.get("episode_files")
    existing_files = existing.get("episode_files")
    if isinstance(duplicate_files, list) and (
        not isinstance(existing_files, list) or len(duplicate_files) >= len(existing_files)
    ):
        existing["episode_files"] = duplicate_files
    for field in ("media_info", "media_tags", "quality_tag"):
        if duplicate.get(field):
            existing[field] = duplicate[field]
    if _expected_episode_count(existing) is None and duplicate.get("episodes"):
        existing["episodes"] = duplicate["episodes"]
    if str(existing.get("manual_verification_reason") or "").startswith("Duplicate metadata title "):
        existing["manual_verification_required"] = False
        existing["manual_verification_reason"] = ""
        existing.pop("duplicate_title_conflict", None)

def _normalize_duplicate_title_conflicts(library: list[dict[str, Any]]) -> bool:
    changed = False
    seen: list[dict[str, Any]] = []
    for anime in library:
        if not isinstance(anime, dict):
            continue
        conflict = _find_duplicate_title_conflict(seen, anime)
        if conflict is not None:
            _resolve_duplicate_title_conflict(anime, conflict)
            changed = True
        seen.append(anime)
    return changed


def _update_imported_anime(existing: dict[str, Any], candidate: dict[str, Any]) -> None:
    preserved = {
        "monitored": existing.get("monitored", True),
        "quality_resolution": _quality_resolution(existing),
        "quality_profile": existing.get("quality_profile", _quality_profile_label(existing)),
        "library_id": existing.get("library_id", candidate.get("library_id")),
    }
    for queue_field in ("download_queue", "download_queues"):
        if queue_field in existing:
            preserved[queue_field] = existing[queue_field]
    local_updates = {
        "local_path": candidate["local_path"],
        "episode_files": candidate["episode_files"],
        "episodes": candidate["episodes"],
    }
    if candidate.get("manual_verification_required") and not existing.get("manual_verification_required", False):
        existing.update(local_updates)
        existing.setdefault("metadata_search_titles", candidate.get("metadata_search_titles", []))
        existing.setdefault("metadata_candidates", candidate.get("metadata_candidates", []))
    else:
        existing.update(candidate)
    existing.update(preserved)
    _refresh_media_tag(existing)
    _refresh_library_state(existing)


def _normalize_anilist_reconciliation_state(anime: dict[str, Any]) -> bool:
    if anime.get("manual_verification_required"):
        return False
    source_name = _metadata_source_name(anime)
    if source_name == "AniList" or _anilist_reconciliation_pending(anime):
        return False
    if source_name in {"anime-offline-database", "Kitsu", "TMDB"} or _provider_id_value(anime, "anilist"):
        _mark_anilist_reconciliation_pending(anime, "Final AniList reconciliation is pending.")
        anime.pop("anilist_metadata_checked_at", None)
        return True
    return False


def _refresh_media_tags(library: list[dict[str, Any]], force: bool = False) -> dict[str, int]:
    summary = {"updated": 0, "skipped": 0, "unknown": 0}
    for anime in library:
        result = _refresh_media_tag(anime, force=force)
        summary[result] += 1
    return summary


def _refresh_media_tag(anime: dict[str, Any], force: bool = False) -> str:
    if _has_resolved_media_quality(anime) and not force:
        _apply_quality_media_tag(anime, str(anime["quality_tag"]))
        return "skipped"

    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list) or not episode_files:
        anime.setdefault("media_tags", [])
        return "unknown"

    media_info = anime.get("media_info")
    if force or not isinstance(media_info, dict) or not media_info.get("height"):
        media_info = _sample_media_info([Path(path) for path in episode_files if isinstance(path, str)])
        anime["media_info"] = media_info

    quality_tag = media_info.get("quality_tag") if isinstance(media_info, dict) else None
    if not quality_tag:
        anime.setdefault("media_tags", [])
        return "unknown"

    anime["quality_tag"] = quality_tag
    _apply_quality_media_tag(anime, quality_tag)
    return "updated"


def _has_resolved_media_quality(anime: dict[str, Any]) -> bool:
    media_info = anime.get("media_info")
    if not isinstance(media_info, dict):
        return False
    return (
        bool(anime.get("quality_tag"))
        and isinstance(media_info.get("width"), int)
        and isinstance(media_info.get("height"), int)
        and media_info["width"] > 0
        and media_info["height"] > 0
    )


def _apply_quality_media_tag(anime: dict[str, Any], quality_tag: str) -> None:
    media_tags = [
        tag
        for tag in anime.get("media_tags", [])
        if tag != quality_tag and not _is_resolution_media_tag(tag)
    ]
    anime["media_tags"] = [quality_tag, *media_tags]


def _is_resolution_media_tag(value: Any) -> bool:
    return bool(re.fullmatch(r"\d{3,4}p", str(value or "").strip().casefold()))


def _sample_media_info(media_files: list[Path]) -> dict[str, Any]:
    for media_file in media_files:
        info = _video_dimensions(media_file)
        if info:
            width, height = info
            return {
                "sample_file": str(media_file.resolve()),
                "probe": "ffprobe",
                "width": width,
                "height": height,
                "quality_tag": _quality_tag(width, height),
            }
    return {}


def _video_dimensions(media_file: Path) -> tuple[int, int] | None:
    return _ffprobe_dimensions(media_file)


def _ffprobe_dimensions(media_file: Path) -> tuple[int, int] | None:
    ffprobe = _ffprobe_path()
    if ffprobe is None:
        return None

    try:
        completed = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "json",
                str(media_file),
            ],
            capture_output=True,
            check=False,
            encoding="utf-8",
            errors="replace",
            timeout=FFPROBE_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    if completed.returncode != 0:
        return None

    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return None

    streams = data.get("streams")
    if not isinstance(streams, list) or not streams:
        return None

    width = streams[0].get("width")
    height = streams[0].get("height")
    if isinstance(width, int) and isinstance(height, int) and width > 0 and height > 0:
        return width, height
    return None


def _ffprobe_path() -> str | None:
    configured_path = os.environ.get("NYAARR_FFPROBE_PATH", "").strip()
    if configured_path:
        return configured_path
    bundled_path = Path(__file__).resolve().parent.parent / "tools" / "ffmpeg" / "bin" / "ffprobe.exe"
    if bundled_path.exists():
        return str(bundled_path)
    return shutil.which("ffprobe")


def _matroska_dimensions(media_file: Path) -> tuple[int, int] | None:
    data = _read_file_prefix(media_file)
    tracks_offset = data.find(b"\x16\x54\xae\x6b")
    if tracks_offset < 0:
        return None
    tracks = _read_ebml_element(data, tracks_offset)
    if tracks is None:
        return None
    for entry in _iter_ebml_children(data, tracks["content_start"], tracks["content_end"]):
        if entry["id"] != 0xAE:
            continue
        track_type = None
        video_dimensions = None
        for child in _iter_ebml_children(data, entry["content_start"], entry["content_end"]):
            if child["id"] == 0x83:
                track_type = _ebml_uint(data[child["content_start"]:child["content_end"]])
            elif child["id"] == 0xE0:
                video_dimensions = _matroska_video_dimensions(data, child["content_start"], child["content_end"])
        if track_type == 1 and video_dimensions is not None:
            return video_dimensions
    return None


def _matroska_video_dimensions(data: bytes, start: int, end: int) -> tuple[int, int] | None:
    width = None
    height = None
    for child in _iter_ebml_children(data, start, end):
        if child["id"] == 0xB0:
            width = _ebml_uint(data[child["content_start"]:child["content_end"]])
        elif child["id"] == 0xBA:
            height = _ebml_uint(data[child["content_start"]:child["content_end"]])
    if width and height:
        return width, height
    return None


def _read_ebml_element(data: bytes, offset: int) -> dict[str, int] | None:
    element_id, id_length = _read_ebml_id(data, offset)
    if element_id is None:
        return None
    size, size_length = _read_ebml_size(data, offset + id_length)
    if size is None:
        return None
    content_start = offset + id_length + size_length
    content_end = min(content_start + size, len(data))
    return {
        "id": element_id,
        "content_start": content_start,
        "content_end": content_end,
        "end": content_end,
    }


def _iter_ebml_children(data: bytes, start: int, end: int):
    offset = start
    while offset < end:
        element = _read_ebml_element(data, offset)
        if element is None or element["end"] <= offset:
            break
        yield element
        offset = element["end"]


def _read_ebml_id(data: bytes, offset: int) -> tuple[int | None, int]:
    if offset >= len(data):
        return None, 0
    first = data[offset]
    length = _vint_length(first)
    if length is None or offset + length > len(data):
        return None, 0
    value = 0
    for byte in data[offset:offset + length]:
        value = (value << 8) | byte
    return value, length


def _read_ebml_size(data: bytes, offset: int) -> tuple[int | None, int]:
    if offset >= len(data):
        return None, 0
    first = data[offset]
    length = _vint_length(first)
    if length is None or offset + length > len(data):
        return None, 0
    value = first & ((1 << (8 - length)) - 1)
    for byte in data[offset + 1:offset + length]:
        value = (value << 8) | byte
    return value, length


def _vint_length(first_byte: int) -> int | None:
    for length in range(1, 9):
        if first_byte & (1 << (8 - length)):
            return length
    return None


def _ebml_uint(data: bytes) -> int | None:
    if not data:
        return None
    value = 0
    for byte in data:
        value = (value << 8) | byte
    return value


def _mp4_dimensions(media_file: Path) -> tuple[int, int] | None:
    data = _read_file_prefix(media_file)
    return _mp4_dimensions_in_range(data, 0, len(data))


def _read_file_prefix(path: Path) -> bytes:
    with path.open("rb") as media_file:
        return media_file.read(MEDIA_PROBE_BYTES)


def _mp4_dimensions_in_range(data: bytes, start: int, end: int) -> tuple[int, int] | None:
    offset = start
    while offset + 8 <= end:
        size = int.from_bytes(data[offset:offset + 4], "big")
        box_type = data[offset + 4:offset + 8]
        header = 8
        if size == 1 and offset + 16 <= end:
            size = int.from_bytes(data[offset + 8:offset + 16], "big")
            header = 16
        if size < header:
            break
        box_end = min(offset + size, end)
        if box_type in {b"moov", b"trak", b"mdia", b"minf", b"stbl"}:
            dimensions = _mp4_dimensions_in_range(data, offset + header, box_end)
            if dimensions:
                return dimensions
        elif box_type == b"tkhd":
            dimensions = _mp4_tkhd_dimensions(data[offset + header:box_end])
            if dimensions:
                return dimensions
        offset = box_end
    return None


def _mp4_tkhd_dimensions(payload: bytes) -> tuple[int, int] | None:
    if len(payload) < 84:
        return None
    version = payload[0]
    if version == 1:
        width_offset = 88
    else:
        width_offset = 76
    if width_offset + 8 > len(payload):
        return None
    width = struct.unpack(">I", payload[width_offset:width_offset + 4])[0] >> 16
    height = struct.unpack(">I", payload[width_offset + 4:width_offset + 8])[0] >> 16
    if width and height:
        return width, height
    return None


def _quality_tag(width: int, height: int) -> str:
    long_edge = max(width, height)
    short_edge = min(width, height)
    if long_edge >= 3800 or short_edge >= 2160:
        return "2160p"
    if long_edge >= 2500 or short_edge >= 1440:
        return "1440p"
    if long_edge >= 1900 or short_edge >= 1080:
        return "1080p"
    if long_edge >= 1200 or short_edge >= 720:
        return "720p"
    if short_edge >= 576:
        return "576p"
    if short_edge >= 480:
        return "480p"
    return f"{height}p"


def _seed_resolved_metadata_cache_from_library(library: list[dict[str, Any]]) -> None:
    for anime in library:
        if anime.get("manual_verification_required"):
            continue
        search_titles = anime.get("metadata_search_titles")
        if not isinstance(search_titles, list) or not search_titles:
            continue
        if not anime.get("provider_ids") and not anime.get("source", "").startswith("Root Folder Scan +"):
            continue
        _resolved_metadata_cache_store(
            {
                "search_titles": [str(title) for title in search_titles],
                "year": _year_value(anime.get("metadata_year_hint")),
                "season_number": _season_hint_value(anime.get("metadata_season_hint")),
            },
            anime,
        )


def _search_metadata_variants(search_titles: list[str]) -> list[dict[str, Any]]:
    merged_results: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    errors: list[str] = []
    for search_title in search_titles:
        try:
            results, notices = search_anime_metadata(search_title)
        except MetadataProviderError as exc:
            errors.append(str(exc))
            continue
        errors.extend(notices)

        for result in results:
            result_key = _metadata_result_key(result)
            if result_key in seen_ids:
                continue
            seen_ids.add(result_key)
            merged_results.append(result)

    if not merged_results and errors:
        raise MetadataProviderError("; ".join(errors))
    return merged_results


def _best_metadata_match(match_context: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any] | None:
    scored = sorted(
        (
            (_metadata_match_score(match_context, result) + _provider_score_bonus(result) - (index * 0.005), result)
            for index, result in enumerate(results)
            if _metadata_episode_count_compatible(match_context, result)
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scored or scored[0][0] < 0.88:
        return None
    if scored[0][0] >= 1.0:
        return scored[0][1]
    if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.03:
        return None
    return scored[0][1]


def _metadata_match_score(match_context: dict[str, Any], result: dict[str, Any]) -> float:
    search_titles = match_context["search_titles"]
    normalized_search_titles = [_metadata_compare_value(title) for title in search_titles]
    weighted_values = _metadata_confidence_title_values(result)
    scores = [
        _title_match_score(search_title, _metadata_compare_value(value)) + weight
        for search_title in normalized_search_titles
        for value, weight in weighted_values
        if search_title and value
    ]
    score = max(scores or [0.0])
    year_hint = _year_value(match_context.get("year"))
    result_year = _year_value(result.get("year"))
    if year_hint is not None and result_year is not None:
        if year_hint == result_year:
            score += 0.08
        else:
            score -= min(abs(year_hint - result_year) * 0.08, 0.35)

    part_hint = _part_hint_value(match_context.get("part_number"))
    result_part = _metadata_part_hint(result)
    part_matches = part_hint is not None and result_part is not None and part_hint == result_part
    season_hint = _season_hint_value(match_context.get("season_number"))
    result_season = _season_hint_value(result.get("season_number"))
    if season_hint is not None and result_season is not None:
        if season_hint == result_season:
            score += 0.08
        elif not (part_matches and match_context.get("season_hint_source") == "episode_files"):
            score -= 0.35
    if part_hint is not None and result_part is not None:
        if part_matches:
            score += 0.08
        else:
            score -= 0.35
    return score


def _metadata_confidence_title_values(result: dict[str, Any]) -> list[tuple[Any, float]]:
    values: list[tuple[Any, float]] = [
        (result.get("title", ""), 0.04),
        (result.get("original_title", ""), 0.03),
        (result.get("romaji_title", ""), 0.03),
        (result.get("english_title", ""), 0.03),
        (result.get("native_title", ""), 0.0),
    ]
    provider_title = result.get("provider_title")
    if isinstance(provider_title, dict):
        values.extend(
            [
                (provider_title.get("romaji"), 0.03),
                (provider_title.get("english"), 0.03),
                (provider_title.get("native"), 0.0),
            ]
        )
    aliases = result.get("aliases", [])
    if isinstance(aliases, list):
        values.extend((alias, 0.0) for alias in aliases)
    metadata_titles = result.get("metadata_search_titles", [])
    if isinstance(metadata_titles, list):
        values.extend((title, 0.0) for title in metadata_titles)
    return values

def _metadata_episode_count_compatible(match_context: dict[str, Any], metadata: Any) -> bool:
    if not isinstance(metadata, dict):
        return True
    if not _metadata_season_compatible(match_context, metadata):
        return False
    local_count = _int_value(match_context.get("local_episode_count"))
    expected_count = _expected_episode_count(metadata)
    raw_expected_count = _int_value(metadata.get("episodes"))
    if local_count is not None and local_count > 0 and raw_expected_count == 0:
        return False
    if local_count is None or local_count <= 0 or expected_count is None:
        return True
    return local_count <= expected_count


def _metadata_season_compatible(match_context: dict[str, Any], metadata: dict[str, Any]) -> bool:
    result_season = _season_hint_value(metadata.get("season_number"))
    context_season = _season_hint_value(match_context.get("season_number"))
    result_part = _metadata_part_hint(metadata)
    context_part = _part_hint_value(match_context.get("part_number"))
    if context_part is not None and result_part is not None and context_part != result_part:
        return False
    part_matches = context_part is not None and result_part is not None and context_part == result_part
    if context_season is not None and result_season is not None:
        if part_matches and match_context.get("season_hint_source") == "episode_files":
            return True
        return context_season == result_season
    if context_season is None and result_season is not None and result_season > 1:
        if part_matches:
            return True
        return False
    return True


def _provider_score_bonus(result: dict[str, Any]) -> float:
    source = result.get("source")
    if source == "AniList":
        return 0.02
    if source == "anime-offline-database":
        return 0.01
    if source == "Kitsu":
        return 0.005
    return 0.0


def _resolved_metadata_cache_lookup(match_context: dict[str, Any]) -> dict[str, Any] | None:
    cache = _read_resolved_metadata_cache()
    for search_title in match_context["search_titles"]:
        entry = cache.get("resolved", {}).get(_metadata_cache_key(search_title))
        if isinstance(entry, dict) and isinstance(entry.get("metadata"), dict):
            metadata = entry["metadata"]
            if _cache_entry_matches_context(entry, match_context) and _metadata_match_score(match_context, metadata) + _provider_score_bonus(metadata) >= 0.88:
                return metadata
    return None


def _resolved_metadata_cache_store(match_context: dict[str, Any], metadata: dict[str, Any]) -> None:
    search_titles = match_context["search_titles"]
    if not search_titles:
        return

    cache = _read_resolved_metadata_cache()
    cache.setdefault("schema_version", 1)
    resolved = cache.setdefault("resolved", {})
    metadata_entry = _cacheable_metadata(metadata)
    stored_at = datetime.now(timezone.utc).isoformat()
    for search_title in search_titles:
        resolved[_metadata_cache_key(search_title)] = {
            "metadata_season_hint": match_context.get("season_number"),
            "metadata_year_hint": match_context.get("year"),
            "metadata": metadata_entry,
            "search_title": search_title,
            "stored_at": stored_at,
        }
    _write_resolved_metadata_cache(cache)


def _cacheable_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "title",
        "original_title",
        "year",
        "status",
        "episodes",
        "season_number",
        "runtime",
        "genres",
        "aliases",
        "studio",
        "source",
        "rating",
        "synopsis",
        "poster",
        "air_date",
        "next_airing_at",
        "airing_episode",
        "airing_source",
        "provider_ids",
    )
    cached = {field: metadata.get(field) for field in fields}
    cached["source"] = _metadata_source_name(metadata)
    if not isinstance(cached.get("genres"), list):
        cached["genres"] = []
    if not isinstance(cached.get("aliases"), list):
        cached["aliases"] = []
    if not isinstance(cached.get("provider_ids"), dict):
        cached["provider_ids"] = {}
    return cached


def _merge_provider_ids(anime: dict[str, Any], metadata: dict[str, Any]) -> None:
    provider_ids = anime.get("provider_ids") if isinstance(anime.get("provider_ids"), dict) else {}
    merged = dict(provider_ids)
    metadata_ids = metadata.get("provider_ids") if isinstance(metadata.get("provider_ids"), dict) else {}
    for provider, value in metadata_ids.items():
        if value not in (None, ""):
            merged[str(provider)] = value
    poster_anilist_id = _anilist_id_from_poster_url(anime.get("poster"))
    if poster_anilist_id and not merged.get("anilist"):
        merged["anilist"] = poster_anilist_id
    anime["provider_ids"] = merged


def _anilist_id_from_poster_url(value: Any) -> str:
    match = re.search(r"/b[xy](\d+)-", str(value or ""))
    return match.group(1) if match else ""

def _metadata_source_name(metadata: dict[str, Any]) -> str:
    source = str(metadata.get("source") or "Unknown")
    while source.startswith("Root Folder Scan + "):
        source = source.removeprefix("Root Folder Scan + ")
    return source


def _metadata_cache_key(search_title: str) -> str:
    return _metadata_compare_value(search_title)


def _cache_entry_matches_context(entry: dict[str, Any], match_context: dict[str, Any]) -> bool:
    if not _metadata_episode_count_compatible(match_context, entry.get("metadata", {})):
        return False
    context_year = _year_value(match_context.get("year"))
    entry_year = _year_value(entry.get("metadata_year_hint"))
    metadata_year = _year_value(entry.get("metadata", {}).get("year"))
    if context_year is not None:
        if entry_year is not None and entry_year != context_year:
            return False
        if metadata_year is not None and metadata_year != context_year:
            return False

    context_season = _season_hint_value(match_context.get("season_number"))
    entry_season = _season_hint_value(entry.get("metadata_season_hint"))
    metadata_season = _season_hint_value(entry.get("metadata", {}).get("season_number"))
    if context_season is not None:
        if entry_season is not None and entry_season != context_season:
            return False
        if metadata_season is not None and metadata_season != context_season:
            return False
    elif metadata_season is not None and metadata_season > 1:
        return False
    return True


def _read_resolved_metadata_cache() -> dict[str, Any]:
    try:
        with RESOLVED_METADATA_CACHE_PATH.open("r", encoding="utf-8") as cache_file:
            cache = json.load(cache_file)
    except (OSError, json.JSONDecodeError):
        return {"schema_version": 1, "resolved": {}}
    if not isinstance(cache, dict) or not isinstance(cache.get("resolved"), dict):
        return {"schema_version": 1, "resolved": {}}
    return cache


def _write_resolved_metadata_cache(cache: dict[str, Any]) -> None:
    _prune_resolved_metadata_cache(cache)
    RESOLVED_METADATA_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = RESOLVED_METADATA_CACHE_PATH.with_suffix(".json.tmp")
    with temp_path.open("w", encoding="utf-8") as cache_file:
        json.dump(cache, cache_file, indent=2, sort_keys=True)
        cache_file.write("\n")
    os.replace(temp_path, RESOLVED_METADATA_CACHE_PATH)


def _title_match_score(import_normalized: str, candidate_normalized: str) -> float:
    if import_normalized == candidate_normalized:
        return 1.0
    import_tokens = import_normalized.split()
    candidate_tokens = candidate_normalized.split()
    if import_tokens and candidate_tokens:
        import_set = set(import_tokens)
        candidate_set = set(candidate_tokens)
        if len(import_set) >= 3 and import_set.issubset(candidate_set):
            return 0.97
        coverage = len(import_set & candidate_set) / len(import_set)
        if len(import_set) >= 3 and coverage >= 0.86 and len(import_set & candidate_set) >= 3:
            return max(0.9, coverage)
    if candidate_normalized.startswith(import_normalized):
        return max(0.92, SequenceMatcher(None, import_normalized, candidate_normalized).ratio())
    return SequenceMatcher(None, import_normalized, candidate_normalized).ratio()


def _metadata_candidate_preview(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "title": result.get("title", "Unknown title"),
            "original_title": result.get("original_title", "Unknown"),
            "year": result.get("year", "Unknown"),
            "source": result.get("source", "Unknown"),
            "aliases": result.get("aliases", [])[:5],
            "provider_ids": result.get("provider_ids", {}),
        }
        for result in results[:3]
    ]


def _metadata_compare_value(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value).casefold()))


def _metadata_match_context(
    import_title: str,
    *,
    local_episode_count: int | None = None,
    local_season_number: int | None = None,
) -> dict[str, Any]:
    title_season = _season_hint_from_title(import_title)
    season_number = title_season if title_season is not None else _local_episode_file_season_hint_value(local_season_number)
    return {
        "search_titles": _metadata_search_titles(import_title),
        "year": _year_hint_from_title(import_title),
        "season_number": season_number,
        "season_hint_source": "title" if title_season is not None else ("episode_files" if season_number is not None else ""),
        "part_number": _part_hint_from_title(import_title),
        "local_episode_count": local_episode_count,
    }


def _local_episode_file_season_hint(anime: dict[str, Any]) -> int | None:
    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list):
        return None
    seasons = {
        season
        for season in (_episode_file_season_number(path) for path in episode_files)
        if season is not None and season > 0
    }
    return next(iter(seasons)) if len(seasons) == 1 else None


def _year_hint_from_title(value: str) -> int | None:
    match = re.search(r"\b((?:19|20)\d{2})\b", value)
    return int(match.group(1)) if match else None


def _local_episode_file_season_hint_value(value: Any) -> int | None:
    season = _int_value(value)
    return season if season is not None and season > 0 else None


def _episode_file_season_number(value: Any) -> int | None:
    text = str(value or "")
    match = re.search(r"\bS(\d{1,2})E\d{1,3}\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    parts = [part.casefold() for part in re.split(r"[\\/]+", text)]
    for part in parts:
        match = re.fullmatch(r"season\s*(\d{1,2})", part.strip(), flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _season_hint_from_title(value: str) -> int | None:
    match = re.search(r"\bS(\d{1,2})(?:E\d{1,3})?\b", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    match = re.search(r"\bseason\s*(\d{1,2})\b", value, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    if re.search(r"\b(?:2nd|ii)\s+season\b", value, flags=re.IGNORECASE):
        return 2
    if re.search(r"\b(?:3rd|iii)\s+season\b", value, flags=re.IGNORECASE):
        return 3
    return None


def _metadata_part_hint(metadata: dict[str, Any]) -> int | None:
    values: list[Any] = [
        metadata.get("title"),
        metadata.get("original_title"),
    ]
    aliases = metadata.get("aliases")
    if isinstance(aliases, list):
        values.extend(aliases)
    for value in values:
        part = _part_hint_from_title(str(value or ""))
        if part is not None:
            return part
    return None


def _part_hint_from_title(value: str) -> int | None:
    normalized = _metadata_compare_value(value)
    match = re.search(r"\b(?:part|cour)\s*(\d{1,2})\b", normalized)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*cour\b", normalized)
    if match:
        return int(match.group(1))
    if re.search(r"\bzenpen\b", normalized) or "前編" in value:
        return 1
    if re.search(r"\bko?uhen\b", normalized) or "後編" in value:
        return 2
    return None


def _part_hint_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str):
        try:
            part = int(value)
        except ValueError:
            return _part_hint_from_title(value)
        return part if part > 0 else None
    return None


def _year_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        match = re.search(r"\b((?:19|20)\d{2})\b", value)
        if match:
            return int(match.group(1))
    return None


def _season_hint_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return _season_hint_from_title(value)
    return None


def _metadata_result_key(result: dict[str, Any]) -> str:
    provider_ids = result.get("provider_ids", {})
    for provider in ("anilist", "mal", "kitsu", "tmdb"):
        if provider_ids.get(provider):
            return f"{provider}:{provider_ids[provider]}"
    return f"{result.get('source', '')}:{result.get('title', '')}:{result.get('year', '')}".casefold()


def _media_files(folder: Path) -> list[Path]:
    return sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.casefold() in MEDIA_EXTENSIONS
        ),
        key=lambda path: str(path).casefold(),
    )


def _title_from_media_file(path: Path) -> str:
    title = re.sub(r"\bS\d{1,2}E\d{1,3}\b", "", path.stem, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:19|20)\d{2}\b", "", title)
    title = re.sub(r"\b\d{1,3}\b", "", title)
    return title or path.stem


def _clean_import_title(value: str) -> str:
    title = re.sub(r"_+", " ", value)
    title = re.sub(r"(?<!\d)\.+|\.+(?!\d)", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -")
    return title or "Unknown Anime"


def _anime_identity_title(value: str) -> str:
    title = _remove_leading_release_group(value)
    title = re.sub(r"\[[^\]]*(?:[a-f0-9]{8}|1080p|720p|2160p|x26[45]|hevc|aac|flac|dual|web|bd)[^\]]*\]", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\([^)]*(?:batch|1080p|720p|2160p|x26[45]|hevc|aac|flac|dual|web|bd)[^)]*\)", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:S\d{1,2})(?:\s|$)", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\bS\d{1,2}E\d{1,3}\b", " ", title, flags=re.IGNORECASE)
    title = re.sub(r"\b(?:19|20)\d{2}\b", " ", title)
    title = re.sub(r"\b\d{1,3}\s*-\s*\d{1,3}\b", " ", title)
    for pattern in RELEASE_SPEC_PATTERNS:
        title = re.sub(pattern, " ", title, flags=re.IGNORECASE)
    title = re.sub(r"[-_\[\]{}]", " ", title)
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9+.']+", title)
        if token.strip("+") and token.strip("+").casefold() not in RELEASE_SPEC_TOKENS
    ]
    cleaned = " ".join(tokens)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
    return cleaned or value


def _remove_leading_release_group(value: str) -> str:
    return re.sub(r"^\s*\[[^\]]+\]\s*", "", value)


def _metadata_search_titles(import_title: str) -> list[str]:
    titles = [import_title]
    titles.extend(_parenthesized_aliases(import_title))
    titles.append(re.sub(r"\([^)]*\)", " ", import_title))
    cleaned_titles = []
    seen = set()
    for title in titles:
        cleaned = _anime_identity_title(_clean_import_title(title))
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            cleaned_titles.append(cleaned)
    return cleaned_titles or [import_title]


def _parenthesized_aliases(value: str) -> list[str]:
    return [
        match.strip()
        for match in re.findall(r"\(([^)]{3,})\)", value)
        if not _looks_like_release_specs(match)
    ]


def _looks_like_release_specs(value: str) -> bool:
    normalized = value.casefold()
    return (
        any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in RELEASE_SPEC_PATTERNS)
        or bool(re.fullmatch(r"\d{1,3}\s*-\s*\d{1,3}", normalized))
        or bool(re.fullmatch(r"(?:19|20)\d{2}", normalized))
    )


def _stable_path_id(path: Path) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(path).casefold()).strip("-")


def _empty_scan_summary() -> dict[str, int]:
    return {"imported": 0, "updated": 0, "skipped": 0, "verified": 0, "manual_verification": 0}


def load_or_create_session_secret() -> str:
    env_secret = str(os.environ.get("NYAARR_SECRET_KEY") or "").strip()
    if env_secret:
        return env_secret
    with _USER_DATABASE_LOCK:
        SESSION_SECRET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if SESSION_SECRET_PATH.exists():
            try:
                secret = SESSION_SECRET_PATH.read_text(encoding="utf-8").strip()
                if len(secret) >= 32:
                    return secret
            except OSError:
                pass
        secret = secrets.token_urlsafe(48)
        SESSION_SECRET_PATH.write_text(secret + "\n", encoding="utf-8")
        try:
            os.chmod(SESSION_SECRET_PATH, 0o600)
        except OSError:
            pass
        return secret


def superadmin_account() -> dict[str, Any] | None:
    auth = _read_user_database().get("auth")
    if not isinstance(auth, dict):
        return None
    superadmin = auth.get("superadmin")
    if not isinstance(superadmin, dict):
        return None
    username = str(superadmin.get("username") or "").strip()
    password_hash = str(superadmin.get("password_hash") or "").strip()
    if not username or not password_hash:
        return None
    return superadmin


def has_superadmin_account() -> bool:
    return superadmin_account() is not None


def create_superadmin_account(username: str, password: str, confirm_password: str) -> tuple[bool, str]:
    username = username.strip()
    if has_superadmin_account():
        return False, "A superadmin account already exists. Sign in with that account."
    if not _valid_superadmin_username(username):
        return False, "Use a username with 3-64 letters, numbers, dots, underscores, or hyphens."
    password_error = _superadmin_password_error(password, confirm_password)
    if password_error:
        return False, password_error

    database = _read_user_database()
    auth = database.setdefault("auth", _empty_auth_state())
    now = datetime.now(timezone.utc).isoformat()
    auth["superadmin"] = {
        "username": username,
        "password_hash": generate_password_hash(password, method="scrypt"),
        "role": "superadmin",
        "created_at": now,
        "password_updated_at": now,
    }
    _record_event(database, "security", f"Created superadmin account for {username}.")
    _write_user_database(database)
    return True, "Superadmin account created."


def verify_superadmin_login(username: str, password: str) -> bool:
    superadmin = superadmin_account()
    if superadmin is None:
        return False
    if not secrets.compare_digest(str(superadmin.get("username") or ""), username.strip()):
        return False
    password_hash = str(superadmin.get("password_hash") or "")
    try:
        return check_password_hash(password_hash, password)
    except (TypeError, ValueError):
        return False


def _valid_superadmin_username(username: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9._-]{3,64}", username))


def _superadmin_password_error(password: str, confirm_password: str) -> str:
    if password != confirm_password:
        return "Passwords do not match."
    if len(password) < 12:
        return "Use a password with at least 12 characters."
    classes = [
        bool(re.search(r"[a-z]", password)),
        bool(re.search(r"[A-Z]", password)),
        bool(re.search(r"\d", password)),
        bool(re.search(r"[^A-Za-z0-9]", password)),
    ]
    if sum(classes) < 3:
        return "Use at least three of: lowercase, uppercase, number, symbol."
    return ""

def _read_user_database() -> dict[str, Any]:
    with _USER_DATABASE_LOCK:
        database = _state_repository().read()
        if not isinstance(database.get('anime'), list):
            database = _empty_user_database()
        database.setdefault('schema_version', DATABASE_SCHEMA_VERSION)
        if not isinstance(database.get('settings'), dict):
            database['settings'] = _empty_user_database()['settings']
        database['settings'].setdefault('download_client', _empty_download_client_settings())
        if isinstance(database['settings'].get('download_client'), dict):
            for key, value in _empty_download_client_settings().items():
                database['settings']['download_client'].setdefault(key, value)
        database['settings']['preferred_subbers'] = _normalized_preferred_subbers(database['settings'].get('preferred_subbers'))
        database['settings'].setdefault('torrent_confidence_threshold', 70)
        database['settings']['timezone'] = _settings_timezone_value(database['settings'].get('timezone'))
        for key in ('ignored_torrents', 'unmonitored_titles', 'events'):
            if not isinstance(database.get(key), list):
                database[key] = []
        changed = _merge_same_path_root_folder_duplicates(database.get('anime', []))
        changed = _normalize_duplicate_title_conflicts(database.get('anime', [])) or changed
        for anime in database.get('anime', []):
            if not isinstance(anime, dict):
                continue
            anime['quality_resolution'] = _quality_resolution(anime)
            if str(anime.get('quality_profile') or '').strip().casefold().startswith('any '):
                anime['quality_profile'] = _quality_profile_label(anime)
            if _normalize_anilist_reconciliation_state(anime):
                changed = True
            _normalize_torrent_search_state(anime)
            if _clear_stale_manual_selection(anime):
                changed = True
        if _prune_user_database(database):
            changed = True
        if changed:
            _write_user_database(database)
        return database


def _sync_anime_nfo_file(anime: dict[str, Any]) -> bool:
    anilist_id = _provider_id_value(anime, "anilist")
    if not anilist_id:
        return False
    target = _anime_nfo_path(anime)
    if target is None:
        return False
    try:
        content = _anime_nfo_xml(anime, anilist_id)
        if target.exists() and target.read_text(encoding="utf-8") == content:
            return False
        temp_path = target.with_suffix(target.suffix + ".tmp")
        temp_path.write_text(content, encoding="utf-8")
        os.replace(temp_path, target)
        return True
    except OSError:
        return False


def _anime_nfo_path(anime: dict[str, Any]) -> Path | None:
    local_path_value = str(anime.get("local_path") or "").strip()
    if not local_path_value:
        return None
    local_path = Path(local_path_value)
    if local_path.exists() and local_path.is_dir():
        return local_path / "tvshow.nfo"
    if local_path.exists() and local_path.is_file():
        return local_path.with_suffix(".nfo")
    return None


def _anime_nfo_xml(anime: dict[str, Any], anilist_id: str) -> str:
    root = ET.Element("tvshow")
    _nfo_text(root, "title", anime.get("title"))
    _nfo_text(root, "originaltitle", anime.get("original_title"))
    unique_id = ET.SubElement(root, "uniqueid", {"type": "anilist", "default": "true"})
    unique_id.text = anilist_id
    _nfo_text(root, "id", f"anilist:{anilist_id}")
    _nfo_text(root, "plot", anime.get("synopsis"))
    _nfo_text(root, "premiered", anime.get("start_date") or anime.get("air_date"))
    year = _year_value(anime.get("year"))
    if year is not None:
        _nfo_text(root, "year", str(year))
    _nfo_text(root, "status", anime.get("status"))
    _nfo_text(root, "studio", anime.get("studio"))
    for genre in anime.get("genres", []) if isinstance(anime.get("genres"), list) else []:
        _nfo_text(root, "genre", genre)
    poster = str(anime.get("poster") or "").strip()
    if poster:
        thumb = ET.SubElement(root, "thumb", {"aspect": "poster"})
        thumb.text = poster
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="unicode", xml_declaration=False) + "\n"


def _nfo_text(root: ET.Element, tag: str, value: Any) -> None:
    text = str(value or "").strip()
    if not text or text == "Unknown":
        return
    ET.SubElement(root, tag).text = text

def _prune_user_database(database: dict[str, Any]) -> bool:
    changed = _prune_ignored_torrents(database)
    changed = _prune_unmonitored_titles(database) or changed
    library = database.get("anime") if isinstance(database.get("anime"), list) else []
    for anime in library:
        if isinstance(anime, dict):
            changed = _prune_anime_retained_state(anime) or changed
    return changed


def _prune_ignored_torrents(database: dict[str, Any]) -> bool:
    ignored = database.get("ignored_torrents")
    if not isinstance(ignored, list):
        return False
    compact = [item for item in ignored if isinstance(item, dict) and str(item.get("key") or "").strip()]
    compact.sort(key=lambda item: str(item.get("ignored_at") or ""), reverse=True)
    archived: list[dict[str, Any]] = []
    if MAX_IGNORED_TORRENTS > 0 and len(compact) > MAX_IGNORED_TORRENTS:
        archived = compact[MAX_IGNORED_TORRENTS:]
        compact = compact[:MAX_IGNORED_TORRENTS]
    compact.sort(key=lambda item: str(item.get("ignored_at") or ""))
    for item in archived:
        _append_cold_storage_event(IGNORED_TORRENTS_COLD_STORAGE_PATH, "ignore", item)
    if compact == ignored:
        return bool(archived)
    database["ignored_torrents"] = compact
    return True

def _prune_unmonitored_titles(database: dict[str, Any]) -> bool:
    entries = database.get("unmonitored_titles")
    if not isinstance(entries, list):
        database["unmonitored_titles"] = []
        return True
    compact: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in sorted(entries, key=lambda item: str(item.get("recorded_at") or "") if isinstance(item, dict) else "", reverse=True):
        if not isinstance(entry, dict):
            continue
        normalized = _normalized_unmonitored_title_entry(entry)
        if normalized is None:
            continue
        identity = _unmonitored_entry_identity(normalized)
        if identity in seen:
            continue
        seen.add(identity)
        compact.append(normalized)
    archived: list[dict[str, Any]] = []
    if MAX_UNMONITORED_TITLE_ENTRIES > 0 and len(compact) > MAX_UNMONITORED_TITLE_ENTRIES:
        archived = compact[MAX_UNMONITORED_TITLE_ENTRIES:]
        compact = compact[:MAX_UNMONITORED_TITLE_ENTRIES]
    compact.sort(key=lambda item: str(item.get("recorded_at") or ""))
    if archived:
        _archive_unmonitored_title_entries(archived)
    if compact == entries:
        return bool(archived)
    database["unmonitored_titles"] = compact
    return True



def _prune_anime_retained_state(anime: dict[str, Any]) -> bool:
    changed = False
    candidates = anime.get("metadata_candidates")
    if isinstance(candidates, list) and MAX_METADATA_CANDIDATES_PER_ANIME > 0 and len(candidates) > MAX_METADATA_CANDIDATES_PER_ANIME:
        archived_candidates = candidates[MAX_METADATA_CANDIDATES_PER_ANIME:]
        anime["metadata_candidates"] = candidates[:MAX_METADATA_CANDIDATES_PER_ANIME]
        _archive_metadata_candidates(anime, archived_candidates)
        changed = True

    queues = _download_queue_items(anime)
    if queues:
        compact_queues = [_compact_download_queue(anime, queue) for queue in queues if isinstance(queue, dict)]
        retained_queues = _retained_download_queues(compact_queues)
        if retained_queues != compact_queues:
            retained_ids = {id(queue) for queue in retained_queues}
            _archive_download_queues(anime, [queue for queue in compact_queues if id(queue) not in retained_ids])
        if retained_queues != queues:
            anime["download_queues"] = retained_queues
            _sync_primary_download_queue(anime, retained_queues)
            changed = True
    return changed


def _compact_download_queue(anime: dict[str, Any], queue: dict[str, Any]) -> dict[str, Any]:
    compact = dict(queue)
    _archive_queue_field_overflow(anime, compact, "flagged_files", MAX_FLAGGED_FILES_PER_QUEUE)
    _archive_queue_field_overflow(anime, compact, "selected_episode_files", MAX_SELECTED_FILES_PER_QUEUE)
    _archive_queue_field_overflow(anime, compact, "rejected_import_files", MAX_SELECTED_FILES_PER_QUEUE)
    return compact


def _archive_queue_field_overflow(anime: dict[str, Any], queue: dict[str, Any], field: str, limit: int) -> None:
    values = queue.get(field)
    if not isinstance(values, list) or limit <= 0 or len(values) <= limit:
        return
    archived = values[limit:]
    queue[field] = values[:limit]
    _append_cold_storage_event(
        DOWNLOAD_QUEUES_COLD_STORAGE_PATH,
        "queue_field_overflow",
        _cold_queue_payload(anime, queue) | {"field": field, "archived_values": archived},
    )


def _archive_download_queues(anime: dict[str, Any], queues: list[dict[str, Any]]) -> None:
    for queue in queues:
        _append_cold_storage_event(DOWNLOAD_QUEUES_COLD_STORAGE_PATH, "queue_history", _cold_queue_payload(anime, queue))


def _cold_queue_payload(anime: dict[str, Any], queue: dict[str, Any]) -> dict[str, Any]:
    return {
        "anime_library_id": str(anime.get("library_id") or ""),
        "anime_title": str(anime.get("title") or anime.get("original_title") or ""),
        "queue_identity": _queue_identity(queue),
        "queue": queue,
    }


def _archive_metadata_candidates(anime: dict[str, Any], candidates: list[Any]) -> None:
    for candidate in candidates:
        if isinstance(candidate, dict):
            _append_cold_storage_event(
                METADATA_CANDIDATES_COLD_STORAGE_PATH,
                "metadata_candidate",
                {
                    "anime_library_id": str(anime.get("library_id") or ""),
                    "anime_title": str(anime.get("title") or anime.get("original_title") or ""),
                    "candidate": candidate,
                },
            )


def _retained_download_queues(queues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if MAX_QUEUE_HISTORY_PER_ANIME <= 0:
        return queues
    active_statuses = {"submitted", "queued", "downloading", "paused", "stalled", "error", "pending_safety", "flagged"}
    active = [queue for queue in queues if queue.get("status") in active_statuses]
    history = [queue for queue in queues if queue.get("status") not in active_statuses]
    if len(history) <= MAX_QUEUE_HISTORY_PER_ANIME:
        return queues
    history.sort(key=_queue_retention_sort_value, reverse=True)
    kept_history_ids = {id(queue) for queue in history[:MAX_QUEUE_HISTORY_PER_ANIME]}
    return [queue for queue in queues if queue.get("status") in active_statuses or id(queue) in kept_history_ids]


def _queue_retention_sort_value(queue: dict[str, Any]) -> str:
    for key in ("completed_at", "rejected_at", "superseded_at", "queued_at", "ignored_at"):
        value = str(queue.get(key) or "")
        if value:
            return value
    return ""


def _limited_list(value: Any, limit: int) -> list[Any]:
    if not isinstance(value, list):
        return []
    if limit <= 0:
        return value
    return value[:limit]


def _prune_resolved_metadata_cache(cache: dict[str, Any]) -> bool:
    resolved = cache.get("resolved")
    if not isinstance(resolved, dict) or MAX_RESOLVED_METADATA_CACHE_ENTRIES <= 0:
        return False
    if len(resolved) <= MAX_RESOLVED_METADATA_CACHE_ENTRIES:
        return False
    items = list(resolved.items())
    archived = items[:-MAX_RESOLVED_METADATA_CACHE_ENTRIES]
    kept = items[-MAX_RESOLVED_METADATA_CACHE_ENTRIES:]
    for key, value in archived:
        _append_cold_storage_event(RESOLVED_METADATA_COLD_STORAGE_PATH, "resolved_metadata_cache", {"key": key, "value": value})
    cache["resolved"] = dict(kept)
    return True


def _write_user_database(database: dict[str, Any]) -> None:
    _prune_user_database(database)
    with _USER_DATABASE_LOCK:
        _state_repository().write(database)


def _state_repository() -> SQLiteStateRepository:
    configured = os.environ.get('NYAARR_STATE_DATABASE_PATH', '').strip()
    configured_path = str(Path(configured).resolve()) if configured else ''
    key = (str(USER_DATABASE_PATH.resolve()), configured_path)
    repository = _STATE_REPOSITORIES.get(key)
    if repository is None:
        repository = SQLiteStateRepository(USER_DATABASE_PATH, _empty_user_database)
        _STATE_REPOSITORIES[key] = repository
    return repository


def _airing_repository() -> SQLiteAiringRepository:
    database_path = str(_state_repository().database_path.resolve())
    repository = _AIRING_REPOSITORIES.get(database_path)
    if repository is None:
        repository = SQLiteAiringRepository(Path(database_path))
        _AIRING_REPOSITORIES[database_path] = repository
    return repository


def _episode_title_repository() -> SQLiteEpisodeTitleRepository:
    database_path = str(_state_repository().database_path.resolve())
    repository = _EPISODE_TITLE_REPOSITORIES.get(database_path)
    if repository is None:
        repository = SQLiteEpisodeTitleRepository(Path(database_path))
        _EPISODE_TITLE_REPOSITORIES[database_path] = repository
    return repository


def _empty_user_database() -> dict[str, Any]:
    return {
        "schema_version": DATABASE_SCHEMA_VERSION,
        "settings": {
            "root_folder": "",
            "download_client": _empty_download_client_settings(),
            "preferred_subbers": list(DEFAULT_PREFERRED_SUBBERS),
            "torrent_confidence_threshold": 70,
            "timezone": DEFAULT_DISPLAY_TIMEZONE,
        },
        "anime": [],
        "ignored_torrents": [],
        "unmonitored_titles": [],
        "events": [],
    }


def _empty_auth_state() -> dict[str, Any]:
    return {"superadmin": None}

def _empty_download_client_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "implementation": "",
        "name": "",
        "host": "",
        "port": 8080,
        "url_base": "",
        "use_ssl": False,
        "username": "",
        "password": "",
        "category": "nyaarr",
        "recent_priority": "Last",
        "older_priority": "Last",
        "add_paused": False,
        "remote_path_mapping_enabled": False,
        "remote_path": "",
        "local_path": "",
    }


def _download_client_from_form(form: dict[str, Any]) -> tuple[dict[str, Any], str]:
    implementation = str(form.get("implementation") or "").strip()
    if implementation != "qbittorrent":
        return {}, "Nyaarr currently only supports qBittorrent."

    host = str(form.get("host") or "").strip()
    if not host:
        return {}, "Enter the qBittorrent host before saving."

    port = _settings_port_value(form.get("port"))
    if port is None:
        return {}, "Enter a valid qBittorrent port between 1 and 65535."

    client = {
        "enabled": form.get("enabled") == "on",
        "implementation": implementation,
        "name": str(form.get("name") or "qBittorrent").strip() or "qBittorrent",
        "host": host,
        "port": port,
        "url_base": str(form.get("url_base") or "").strip(),
        "use_ssl": form.get("use_ssl") == "on",
        "username": str(form.get("username") or "").strip(),
        "password": str(form.get("password") or ""),
        "category": str(form.get("category") or "nyaarr").strip() or "nyaarr",
        "recent_priority": str(form.get("recent_priority") or "Last").strip() or "Last",
        "older_priority": str(form.get("older_priority") or "Last").strip() or "Last",
        "add_paused": form.get("add_paused") == "on",
        "remote_path_mapping_enabled": form.get("remote_path_mapping_enabled") == "on",
        "remote_path": str(form.get("remote_path") or "").strip(),
        "local_path": str(form.get("local_path") or "").strip(),
    }
    return client, ""


def _download_client_base_url(client: dict[str, Any]) -> str:
    host = str(client.get("host") or "").strip()
    port = _settings_port_value(client.get("port"))
    if not host or port is None:
        return ""
    scheme = "https" if client.get("use_ssl") else "http"
    url_base = str(client.get("url_base") or "").strip().strip("/")
    base_url = f"{scheme}://{host}:{port}"
    if url_base:
        base_url = f"{base_url}/{url_base}"
    return base_url.rstrip("/")


def _settings_port_value(value: Any) -> int | None:
    try:
        port = int(str(value or "").strip())
    except ValueError:
        return None
    if 1 <= port <= 65535:
        return port
    return None


def _calendar_anchor_date(value: str | None, settings: dict[str, Any] | None = None) -> date:
    if value:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            pass
    return _display_today(settings)


def _calendar_period_bounds(view: str, anchor: date) -> tuple[date, date]:
    if view == "month":
        first_day = anchor.replace(day=1)
        grid_start = first_day - timedelta(days=first_day.weekday())
        next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
        last_day = next_month - timedelta(days=1)
        grid_end = last_day + timedelta(days=6 - last_day.weekday())
        return grid_start, grid_end

    week_start = anchor - timedelta(days=anchor.weekday())
    return week_start, week_start + timedelta(days=6)


def _calendar_days(
    period_start: date,
    period_end: date,
    library: list[dict[str, Any]],
    display_month: int | None,
    settings: dict[str, Any] | None = None,
    schedule_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    items_by_date: dict[str, list[dict[str, Any]]] = {}
    anime_by_media_id = {
        _provider_id_value(anime, "anilist"): anime
        for anime in library
        if _provider_id_value(anime, "anilist")
    }


    scheduled_identities: set[tuple[str, int]] = set()
    for record in schedule_records or []:
        anime = anime_by_media_id.get(str(record.get("media_id") or ""))
        airing_at = _parse_airing_datetime(record.get("airing_at"))
        episode = _int_value(record.get("episode"))
        if anime is None or airing_at is None or episode is None:
            continue
        scheduled_date = airing_at.astimezone(_display_timezone(settings)).date()
        if scheduled_date < period_start or scheduled_date > period_end:
            continue
        items_by_date.setdefault(scheduled_date.isoformat(), []).append(
            _calendar_item(anime, settings, record)
        )
        scheduled_identities.add((str(record.get("media_id") or ""), episode))
    for anime in library:
        media_id = _provider_id_value(anime, "anilist")
        next_episode = _int_value(anime.get("airing_episode"))
        if media_id and next_episode is not None and (media_id, next_episode) in scheduled_identities:
            continue
        scheduled_date = _anime_air_date(anime, settings)
        if scheduled_date is None or scheduled_date < period_start or scheduled_date > period_end:
            continue
        items_by_date.setdefault(scheduled_date.isoformat(), []).append(_calendar_item(anime, settings))

    days = []
    current = period_start
    while current <= period_end:
        key = current.isoformat()
        days.append(
            {
                "date": key,
                "day_name": current.strftime("%a"),
                "day_number": str(current.day),
                "month_name": current.strftime("%b"),
                "date_label": _display_date_label(current, include_year=False),
                "is_today": current == _display_today(settings),
                "is_current_month": display_month is None or current.month == display_month,
                "entries": sorted(items_by_date.get(key, []), key=lambda item: (item["time"], item["title"].casefold())),
            }
        )
        current += timedelta(days=1)
    return days


def _calendar_item(
    anime: dict[str, Any],
    settings: dict[str, Any] | None = None,
    schedule_record: dict[str, Any] | None = None,
) -> dict[str, str]:
    schedule_record = schedule_record or {}
    next_airing_at = _parse_airing_datetime(schedule_record.get("airing_at") or anime.get("next_airing_at"))
    display_time = next_airing_at.astimezone(_display_timezone(settings)) if next_airing_at else None
    episode = str(schedule_record.get("episode") or anime.get("airing_episode") or "").strip()
    title = str(anime.get("title") or "Unknown anime")
    return {
        "title": title,
        "time": f"{display_time:%H:%M} {display_timezone_label(settings)}" if display_time else "TBA",
        "episode": f"Episode {episode}" if episode else "Next episode",
        "poster": str(anime.get("poster") or ""),
        "status": str(anime.get("status") or "Unknown"),
        "library_state": str(anime.get("library_state") or "Unknown"),
        "source": str(anime.get("airing_source") or anime.get("source") or "Unknown"),
        "precision": str(schedule_record.get("precision") or "exact"),
    }


def _upcoming_calendar_entries(library: list[dict[str, Any]], limit: int = 8, settings: dict[str, Any] | None = None) -> list[dict[str, str]]:
    today = _display_today(settings)
    entries = []
    media_ids = [_provider_id_value(anime, "anilist") for anime in library]
    media_ids = [media_id for media_id in media_ids if media_id]
    now = datetime.now(timezone.utc)
    cached = _airing_repository().for_range(
        media_ids,
        now.isoformat().replace("+00:00", "Z"),
        (now + timedelta(days=365)).isoformat().replace("+00:00", "Z"),
    )


def _explicit_ongoing_anime(anime: dict[str, Any]) -> bool:
    status = str(anime.get("status") or "").strip().casefold()
    airing_state = str(anime.get("airing_state") or anime.get("airing_tag") or "").strip().casefold()
    return status in {"releasing", "airing", "currently airing", "ongoing", "current"} or airing_state == "airing"
    anime_by_media_id = {
        _provider_id_value(anime, "anilist"): anime
        for anime in library if _provider_id_value(anime, "anilist")
    }
    for record in cached:
        anime = anime_by_media_id.get(str(record.get("media_id") or ""))
        parsed = _parse_airing_datetime(record.get("airing_at"))
        if anime is None or parsed is None:
            continue
        item = _calendar_item(anime, settings, record)
        item["date"] = parsed.astimezone(_display_timezone(settings)).date().isoformat()
        item["date_label"] = _display_date_label(parsed.astimezone(_display_timezone(settings)).date(), include_year=False)
        entries.append(item)
    if entries:
        return sorted(entries, key=lambda item: (item["date"], item["time"], item["title"].casefold()))[:limit]
    for anime in library:
        scheduled_date = _anime_air_date(anime, settings)
        if scheduled_date is None or scheduled_date < today:
            continue
        item = _calendar_item(anime, settings)
        item["date"] = scheduled_date.isoformat()
        item["date_label"] = _display_date_label(scheduled_date, include_year=False)
        entries.append(item)
    return sorted(entries, key=lambda item: (item["date"], item["time"], item["title"].casefold()))[:limit]


def _anime_air_date(anime: dict[str, Any], settings: dict[str, Any] | None = None) -> date | None:
    next_airing_at = _parse_airing_datetime(anime.get("next_airing_at"))
    if next_airing_at is not None:
        return next_airing_at.astimezone(_display_timezone(settings)).date()

    air_date = str(anime.get("air_date") or "").strip()
    if not air_date:
        return None
    try:
        return datetime.strptime(air_date, "%Y-%m-%d").date()
    except ValueError:
        return None


def _parse_airing_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _display_date_label(value: date, *, include_year: bool = True) -> str:
    if include_year:
        return value.strftime("%d %b %Y")
    return value.strftime("%d %b")

def _calendar_period_label(view: str, period_start: date, period_end: date) -> str:
    if view == "month":
        focus = period_start + timedelta(days=15)
        if period_start.month != focus.month:
            focus = period_end - timedelta(days=15)
        return focus.strftime("%B %Y")
    if period_start.month == period_end.month:
        return f"{period_start.day}-{period_end.day} {period_start.strftime('%b')} {period_end.year}"
    return f"{period_start.day} {period_start.strftime('%b')} - {period_end.day} {period_end.strftime('%b')} {period_end.year}"


def _calendar_shift_date(view: str, anchor: date, direction: int) -> date:
    if view == "month":
        month_index = (anchor.year * 12) + (anchor.month - 1) + direction
        year = month_index // 12
        month = (month_index % 12) + 1
        day = min(anchor.day, _month_last_day(year, month))
        return date(year, month, day)
    return anchor + timedelta(days=7 * direction)


def _month_last_day(year: int, month: int) -> int:
    first_day = date(year, month, 1)
    next_month = (first_day.replace(day=28) + timedelta(days=4)).replace(day=1)
    return (next_month - timedelta(days=1)).day


def _is_currently_airing(anime: dict[str, Any]) -> bool:
    return _airing_state(anime) == "Airing"


def _should_refresh_airing_schedule(anime: dict[str, Any], now: float, force: bool) -> bool:
    if force:
        return True
    if _is_finished_status(anime.get("status")):
        return False

    checked_at = _parse_checked_at(anime.get("airing_schedule_checked_at"))
    if checked_at is not None and now - checked_at < AIRING_REFRESH_MAX_AGE_SECONDS:
        return False
    return _airing_state(anime) in {"Airing", "Not Yet Aired", "Unknown"}


def _refresh_anime_airing_schedule(anime: dict[str, Any], now: float) -> bool:
    notices: list[str] = []
    anilist_id = _provider_id_value(anime, "anilist") or _anilist_id_from_poster_url(anime.get("poster"))
    if anilist_id:
        try:
            match = search_anilist_by_id(anilist_id)
        except MetadataProviderError as exc:
            notices.append(str(exc))
        else:
            if match is not None:
                _apply_airing_schedule_metadata(anime, match)
                _mark_airing_schedule_checked(anime, now, "")
                if notices:
                    anime["airing_schedule_notices"] = notices
                else:
                    anime.pop("airing_schedule_notices", None)
                _refresh_library_state(anime)
                return True

    search_title = _airing_search_title(anime)
    if not search_title:
        _mark_airing_schedule_checked(anime, now, "No title available for schedule refresh.")
        return False

    try:
        results, search_notices = search_anime_metadata(search_title)
    except MetadataProviderError as exc:
        _mark_airing_schedule_checked(anime, now, "; ".join([*notices, str(exc)]))
        return False
    notices.extend(search_notices)

    match = _best_schedule_match(anime, results)
    if match is None:
        _mark_airing_schedule_checked(anime, now, "No confident metadata match was found for schedule refresh.")
        return False

    _apply_airing_schedule_metadata(anime, match)
    _mark_airing_schedule_checked(anime, now, "")
    if notices:
        anime["airing_schedule_notices"] = notices
    else:
        anime.pop("airing_schedule_notices", None)
    _refresh_library_state(anime)
    return True


def _best_schedule_match(anime: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any] | None:
    provider_match = _provider_id_match(anime, results)
    if provider_match is not None:
        return provider_match

    match_context = _metadata_match_context(_airing_search_title(anime))
    match_context["year"] = _year_value(anime.get("year"))
    match_context["season_number"] = _season_hint_value(anime.get("season_number"))
    return _best_metadata_match(match_context, results)


def _provider_id_value(anime: dict[str, Any], provider: str) -> str:
    provider_ids = anime.get("provider_ids")
    if not isinstance(provider_ids, dict):
        return ""
    value = provider_ids.get(provider)
    return str(value).strip() if value not in (None, "") else ""


def _provider_id_match(anime: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any] | None:
    provider_ids = anime.get("provider_ids")
    if not isinstance(provider_ids, dict):
        return None

    normalized_ids = {
        str(provider): str(value)
        for provider, value in provider_ids.items()
        if value not in (None, "")
    }
    if not normalized_ids:
        return None

    for result in results:
        result_ids = result.get("provider_ids")
        if not isinstance(result_ids, dict):
            continue
        for provider, value in result_ids.items():
            if str(provider) in normalized_ids and str(value) == normalized_ids[str(provider)]:
                return result
    return None


def _apply_airing_schedule_metadata(anime: dict[str, Any], metadata: dict[str, Any]) -> None:
    for field in ("status", "air_date", "provider_ids"):
        value = metadata.get(field)
        if value not in (None, ""):
            anime[field] = value
    for field in ("next_airing_at", "airing_episode", "airing_source"):
        if field in metadata:
            anime[field] = str(metadata.get(field) or "")
    anime["airing_schedule_source"] = _metadata_source_name(metadata)


def _airing_search_title(anime: dict[str, Any]) -> str:
    for field in ("title", "original_title"):
        value = str(anime.get(field) or "").strip()
        if value:
            return value
    search_titles = anime.get("metadata_search_titles")
    if isinstance(search_titles, list):
        for value in search_titles:
            text = str(value or "").strip()
            if text:
                return text
    return ""


def _mark_airing_schedule_checked(anime: dict[str, Any], now: float, error: str) -> None:
    anime["airing_schedule_checked_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")
    if error:
        anime["airing_schedule_error"] = error
    else:
        anime.pop("airing_schedule_error", None)


def _parse_checked_at(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _schedule_snapshot(anime: dict[str, Any]) -> tuple[Any, ...]:
    return (
        anime.get("status"),
        anime.get("air_date"),
        anime.get("next_airing_at"),
        anime.get("airing_episode"),
        anime.get("airing_source"),
        anime.get("airing_state"),
        anime.get("airing_tag"),
        anime.get("airing_tag_class"),
        anime.get("airing_schedule_checked_at"),
        anime.get("airing_schedule_error"),
    )
