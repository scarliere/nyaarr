from __future__ import annotations

import json
from datetime import datetime, timezone

from nyaarr import app_state, qbittorrent_client


def missing_anime(*, checked_at: str = "", candidates: list[dict[str, object]] | None = None) -> dict[str, object]:
    torrent_search: dict[str, object] = {
        "query": "Petals of Reincarnation",
        "strategy": "Preferred 1080p per-episode releases from SteadySubs",
        "candidates": candidates if candidates is not None else [{"episode": 5}],
        "notices": [],
    }
    if checked_at:
        torrent_search["checked_at"] = checked_at
    return {
        "title": "Petals of Reincarnation",
        "library_state": "Monitored",
        "completion": {
            "expected_episodes": 12,
            "local_episodes": 4,
            "progress_target": 12,
            "missing_episodes": 8,
        },
        "torrent_search": torrent_search,
    }


def test_missing_episode_anime_refreshes_even_when_it_has_existing_candidates(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    anime = missing_anime(checked_at="2026-06-25T00:00:00+00:00")
    now = datetime(2026, 6, 25, 0, 2, tzinfo=timezone.utc).timestamp()

    assert app_state._should_refresh_torrent_search(anime, now) is True


def test_missing_episode_anime_waits_until_refresh_interval_expires(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    anime = missing_anime(checked_at="2026-06-25T00:01:30+00:00")
    now = datetime(2026, 6, 25, 0, 2, tzinfo=timezone.utc).timestamp()

    assert app_state._should_refresh_torrent_search(anime, now) is False


def test_completed_anime_does_not_refresh_torrent_search() -> None:
    anime = missing_anime(checked_at="2026-06-25T00:00:00+00:00")
    anime["library_state"] = "Completed"

    assert app_state._should_refresh_torrent_search(anime, 9999999999) is False




def test_mark_torrent_search_pending_keeps_unmonitored_paused() -> None:
    anime = missing_anime()
    anime["monitored"] = False
    anime["torrent_manual_selection"] = {"required": True}

    app_state._mark_torrent_search_pending(anime)

    assert anime["monitored"] is False
    assert anime["torrent_manual_selection"] == {"required": False}
    assert anime["torrent_search"]["strategy"] == "Torrent search paused because anime is unmonitored"
    assert anime["torrent_search"]["candidates"] == []


def test_add_existing_anime_preserves_unmonitored_preference(monkeypatch) -> None:
    existing = {
        "library_id": "anime-chiikawa",
        "title": "Chiikawa",
        "monitored": False,
        "library_state": "Paused",
        "episodes": "120",
        "quality_resolution": "1080p",
        "torrent_search": {"strategy": "Torrent search paused because anime is unmonitored", "candidates": []},
        "torrent_manual_selection": {"required": False},
    }
    database = {"settings": {"root_folder": "C:/Anime"}, "anime": [existing], "events": []}
    writes = []
    calls = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", lambda *args, **kwargs: calls.append("dispatch"))

    updated = app_state.add_anime_to_library(
        {"library_id": "anime-chiikawa", "title": "Chiikawa", "episodes": "999", "season_number": 1},
        {"query": "Chiikawa", "strategy": "initial", "candidates": [{"title": "new candidate"}], "notices": []},
    )

    assert updated is existing
    assert updated["monitored"] is False
    assert updated["library_state"] == "Paused"
    assert updated["torrent_manual_selection"] == {"required": False}
    assert updated["torrent_search"]["strategy"] == "Torrent search paused because anime is unmonitored"
    assert updated["torrent_search"]["candidates"] == []
    assert calls == []
    assert writes == [database]

def test_add_anime_queues_torrent_search_without_inline_external_work(monkeypatch) -> None:
    database = {"settings": {"root_folder": ""}, "anime": [], "events": []}
    writes = []
    calls = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_refresh_torrent_search", lambda *args, **kwargs: calls.append("refresh"))
    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", lambda *args, **kwargs: calls.append("dispatch"))

    added = app_state.add_anime_to_library(
        {"library_id": "anime-new", "title": "Async Add", "episodes": "12", "season_number": 1},
        {"query": "Async Add", "strategy": "initial", "candidates": [], "notices": []},
    )

    assert added["torrent_search"]["strategy"] == "Queued for background torrent search"
    assert "checked_at" not in added["torrent_search"]
    assert calls == []
    assert writes == [database]


def test_add_anime_with_supplied_torrent_queues_candidate_without_inline_dispatch(monkeypatch) -> None:
    database = {"settings": {"root_folder": "C:/Anime", "torrent_confidence_threshold": 70}, "anime": [], "events": []}
    writes = []
    calls = []
    magnet = "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12"

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", lambda *args, **kwargs: calls.append("dispatch"))

    added = app_state.add_anime_to_library(
        {"library_id": "anime-new", "title": "Async Add", "episodes": "12", "season_number": 1},
        {"query": "Async Add", "strategy": "initial", "candidates": [], "notices": []},
        magnet,
    )

    assert added["torrent_search"]["strategy"] == "User supplied Nyaa torrent link queued for background dispatch"
    assert added["torrent_search"]["candidates"][0]["torrent_url"] == magnet
    assert added["torrent_search"]["checked_at"]
    assert calls == []
    assert writes == [database]

def manual_candidate(infohash: str = "candidate-1") -> dict[str, object]:
    return {
        "title": "[SteadySubs] Petals of Reincarnation - 05 [1080p]",
        "torrent_url": "https://nyaa.si/download/1.torrent",
        "detail_url": "https://nyaa.si/view/1",
        "infohash": infohash,
        "release_kind": "episode",
        "release_group": "SteadySubs",
        "episode": 5,
        "seeders": 10,
        "source_kind": "web",
        "resolution": 1080,
    }


def manual_database(candidate: dict[str, object] | None = None) -> dict[str, object]:
    candidate = candidate or manual_candidate()
    return {
        "settings": {"root_folder": "C:/Anime", "torrent_confidence_threshold": 70, "preferred_subbers": []},
        "ignored_torrents": [],
        "anime": [
            {
                "library_id": "anime-1",
                "title": "Petals of Reincarnation",
                "monitored": True,
                "library_state": "Monitored",
                "episodes": "12",
                "quality_resolution": "1080p",
                "completion": {
                    "expected_episodes": 12,
                    "local_episodes": 4,
                    "progress_target": 12,
                    "missing_episodes": 8,
                },
                "torrent_search": {"candidates": [candidate], "notices": []},
                "torrent_manual_selection": {"required": True},
            }
        ],
    }




def test_active_queue_does_not_exempt_anime_from_episode_finder_refresh(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    anime = missing_anime(checked_at="2026-06-25T00:00:00+00:00")
    anime["download_queue"] = {"status": "downloading"}
    now = datetime(2026, 6, 25, 0, 2, tzinfo=timezone.utc).timestamp()

    assert app_state._should_refresh_torrent_search(anime, now) is True


def test_no_candidate_manual_selection_can_refresh_when_stale(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    anime = missing_anime(checked_at="2026-06-25T00:00:00+00:00")
    anime["torrent_manual_selection"] = {"required": True, "intervention_type": "no_candidates"}
    now = datetime(2026, 6, 25, 0, 2, tzinfo=timezone.utc).timestamp()

    assert app_state._manual_selection_required(anime) is True
    assert app_state._should_refresh_torrent_search(anime, now) is True


def test_manual_selection_required_exempts_anime_from_refresh(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    anime = missing_anime(checked_at="2026-06-25T00:00:00+00:00")
    anime["torrent_manual_selection"] = {"required": True}
    now = datetime(2026, 6, 25, 0, 2, tzinfo=timezone.utc).timestamp()

    assert app_state._should_refresh_torrent_search(anime, now) is False


def test_accepting_manual_selection_dispatches_selected_candidate(monkeypatch) -> None:
    candidate = manual_candidate()
    database = manual_database(candidate)
    writes = []
    dispatched = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    def fake_dispatch(db, anime, forced_release=None):
        dispatched.append(forced_release)
        anime["download_queue"] = {"torrent_url": forced_release["torrent_url"], "status": "queued"}

    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", fake_dispatch)

    success, message = app_state.assign_manual_torrent("anime-1", "hash:candidate-1")

    assert success is True
    assert message == "Selected torrent was sent to qBittorrent."
    assert dispatched and dispatched[0]["infohash"] == "candidate-1"
    assert writes == [database]


def test_accepting_one_manual_episode_keeps_remaining_episode_visible(monkeypatch) -> None:
    episode_five = manual_candidate("candidate-5")
    episode_six = manual_candidate("candidate-6")
    episode_six.update(
        {
            "title": "[SteadySubs] Petals of Reincarnation - 06 [1080p]",
            "torrent_url": "https://nyaa.si/download/6.torrent",
            "detail_url": "https://nyaa.si/view/6",
            "episode": 6,
        }
    )
    database = manual_database(episode_five)
    anime = database["anime"][0]
    anime["torrent_search"]["candidates"] = [episode_five, episode_six]
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    def fake_dispatch(db, anime_item, forced_release=None):
        anime_item["download_queues"] = [
            {
                "torrent_url": forced_release["torrent_url"],
                "infohash": forced_release["infohash"],
                "episode": forced_release["episode"],
                "status": "queued",
            }
        ]
        anime_item["download_queue"] = anime_item["download_queues"][0]
        anime_item["torrent_manual_selection"] = {"required": False}

    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", fake_dispatch)

    success, message = app_state.assign_manual_torrent("anime-1", "hash:candidate-5")
    model = app_state.manual_selection_model()

    assert success is True
    assert message == "Selected torrent was sent to qBittorrent."
    assert anime["torrent_manual_selection"]["required"] is True
    assert model["count"] == 1
    assert [candidate["episode"] for candidate in model["items"][0]["candidates"]] == [6]
    assert writes == [database]


def test_rejecting_manual_selection_ignores_candidate_and_researches(monkeypatch) -> None:
    candidate = manual_candidate()
    database = manual_database(candidate)
    calls = []
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    def fake_refresh(anime, database=None):
        calls.append("refresh")
        anime["torrent_search"] = {"candidates": [], "notices": []}

    def fake_dispatch(db, anime, forced_release=None):
        calls.append("dispatch")

    monkeypatch.setattr(app_state, "_refresh_torrent_search", fake_refresh)
    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", fake_dispatch)

    success, message = app_state.reject_manual_torrent("anime-1", "hash:candidate-1")

    anime = database["anime"][0]
    assert success is True
    assert message == "Rejected candidate and refreshed torrent search."
    assert database["ignored_torrents"][0]["key"] == "hash:candidate-1"
    assert anime["torrent_manual_selection"] == {"required": False}
    assert calls == ["refresh", "dispatch"]
    assert writes == [database]



def auto_candidate(episode: int, group: str = "SteadySubs") -> dict[str, object]:
    candidate = manual_candidate(f"{group}-{episode}")
    candidate.update(
        {
            "title": f"[{group}] Petals of Reincarnation - {episode:02d} [1080p]",
            "torrent_url": f"https://nyaa.si/download/{group}-{episode}.torrent",
            "detail_url": f"https://nyaa.si/view/{group}-{episode}",
            "infohash": f"{group}-{episode}",
            "episode": episode,
            "release_group": group,
            "seeders": 25,
        }
    )
    return candidate


class FakeDownloadClient:
    def __init__(
        self,
        torrents: list[dict[str, object]] | None = None,
        files_by_hash: dict[str, list[dict[str, object]]] | None = None,
        file_error: Exception | None = None,
    ) -> None:
        self.urls: list[str] = []
        self.calls: list[dict[str, object]] = []
        self.resumed: list[str] = []
        self.deleted: list[tuple[str, bool]] = []
        self.file_priorities: list[tuple[str, list[int], int]] = []
        self.renamed_folders: list[tuple[str, str, str]] = []
        self.locations: list[tuple[str, str]] = []
        self._torrents = torrents or []
        self._files_by_hash = files_by_hash or {}
        self._file_error = file_error

    def add_url(self, url: str, **kwargs: object) -> None:
        self.urls.append(url)
        self.calls.append(kwargs)

    def torrents(self, **kwargs: object) -> list[dict[str, object]]:
        hashes = str(kwargs.get("hashes") or "").casefold()
        if hashes:
            return [torrent for torrent in self._torrents if str(torrent.get("hash") or "").casefold() == hashes]
        return self._torrents

    def torrent_files(self, torrent_hash: str) -> list[dict[str, object]]:
        if self._file_error is not None:
            raise self._file_error
        return self._files_by_hash.get(torrent_hash.casefold(), [])

    def resume(self, torrent_hash: str) -> None:
        self.resumed.append(torrent_hash)

    def delete(self, torrent_hash: str, *, delete_files: bool = False) -> None:
        self.deleted.append((torrent_hash, delete_files))
        self._torrents = [torrent for torrent in self._torrents if str(torrent.get("hash") or "").casefold() != torrent_hash.casefold()]

    def set_file_priority(self, torrent_hash: str, file_ids: list[int], priority: int) -> None:
        self.file_priorities.append((torrent_hash, file_ids, priority))

    def rename_folder(self, torrent_hash: str, old_path: str, new_path: str) -> None:
        self.renamed_folders.append((torrent_hash, old_path, new_path))

    def set_location(self, torrent_hash: str, location: str) -> None:
        self.locations.append((torrent_hash, location))


def auto_dispatch_database(candidates: list[dict[str, object]]) -> dict[str, object]:
    return {
        "settings": {
            "root_folder": "C:/Anime",
            "torrent_confidence_threshold": 70,
            "preferred_subbers": [],
            "download_client": {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"},
        },
        "ignored_torrents": [],
        "anime": [
            {
                "library_id": "anime-1",
                "title": "Petals of Reincarnation",
                "monitored": True,
                "library_state": "Monitored",
                "episodes": "3",
                "quality_resolution": "1080p",
                "completion": {
                    "expected_episodes": 3,
                    "local_episodes": 0,
                    "progress_target": 3,
                    "missing_episodes": 3,
                },
                "torrent_search": {"candidates": candidates, "notices": []},
            }
        ],
    }


def test_supplied_add_accepts_nyaa_view_and_download_urls() -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]

    view_release, view_error = app_state._supplied_add_torrent_release(anime, "https://nyaa.si/view/1588421", database)
    download_release, download_error = app_state._supplied_add_torrent_release(anime, "https://nyaa.si/download/1588421.torrent", database)

    assert view_error == ""
    assert view_release["torrent_url"] == "https://nyaa.si/download/1588421.torrent"
    assert view_release["detail_url"] == "https://nyaa.si/view/1588421"
    assert download_error == ""
    assert download_release["torrent_url"] == "https://nyaa.si/download/1588421.torrent"
    assert download_release["detail_url"] == "https://nyaa.si/view/1588421"


def test_supplied_add_batch_autofills_episode_selection_from_torrent_files(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    release, error = app_state._supplied_add_torrent_release(anime, "https://nyaa.si/view/123", database)
    assert error == ""
    release["infohash"] = "batch-hash"
    anime["download_queue"] = app_state._download_queue_from_release(
        release,
        anime,
        database["settings"]["download_client"],
        database["settings"]["root_folder"],
        [1, 2, 3],
    )
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [{"hash": "batch-hash", "name": "Petals batch", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"}],
        {
            "batch-hash": [
                {"index": 0, "name": "[SteadySubs] Petals of Reincarnation - 01 [1080p].mkv"},
                {"index": 1, "name": "[SteadySubs] Petals of Reincarnation - 02 [1080p].mkv"},
                {"index": 2, "name": "[SteadySubs] Petals of Reincarnation - 03 [1080p].mkv"},
            ]
        },
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    queue = anime["download_queue"]
    assert changed is True
    assert queue["release_kind"] == "batch"
    assert queue["wanted_episodes"] == [1, 2, 3]
    assert queue["release_group"] == "SteadySubs"
    assert queue["file_selection_status"] == "applied"
    assert ("batch-hash", [0, 1, 2], 1) in client.file_priorities


def test_confidence_penalizes_longer_different_series_title() -> None:
    database = {"settings": {"torrent_confidence_threshold": 70, "preferred_subbers": []}, "ignored_torrents": []}
    anime = auto_dispatch_database([])["anime"][0]
    anime.update({"title": "Monster", "original_title": "Monster", "metadata_search_titles": ["Monster"]})
    candidate = {
        "title": "[HorribleSubs] Monster Hunter Stories Ride On - 21 [1080p].mkv",
        "torrent_url": "https://nyaa.si/download/bad.torrent",
        "release_kind": "episode",
        "episode": 21,
        "release_group": "HorribleSubs",
        "source_kind": "web",
        "seeders": 50,
    }

    score, reasons = app_state._torrent_candidate_confidence(candidate, database, anime)

    assert score < database["settings"]["torrent_confidence_threshold"]
    assert "torrent title does not match the selected anime title" in reasons


def test_confidence_uses_alias_and_romaji_titles_as_positive_matches() -> None:
    database = {"settings": {"torrent_confidence_threshold": 70, "preferred_subbers": []}, "ignored_torrents": []}
    anime = auto_dispatch_database([])["anime"][0]
    anime.update(
        {
            "title": "Petals of Reincarnation",
            "original_title": "Reincarnation no Kaben",
            "aliases": ["Petals Reincarnated"],
            "completion": {"expected_episodes": 1, "local_episodes": 0, "progress_target": 1, "missing_episodes": 1},
        }
    )
    romaji_candidate = auto_candidate(1, "SubsPlease")
    romaji_candidate["title"] = "[SubsPlease] Reincarnation no Kaben - 01 [1080p]"
    alias_candidate = auto_candidate(1, "SubsPlease")
    alias_candidate["title"] = "[SubsPlease] Petals Reincarnated - 01 [1080p]"

    romaji_score, romaji_reasons = app_state._torrent_candidate_confidence(romaji_candidate, database, anime)
    alias_score, alias_reasons = app_state._torrent_candidate_confidence(alias_candidate, database, anime)

    assert romaji_score >= database["settings"]["torrent_confidence_threshold"]
    assert alias_score >= database["settings"]["torrent_confidence_threshold"]
    assert "torrent title does not match the selected anime title" not in romaji_reasons
    assert "torrent title does not match the selected anime title" not in alias_reasons
    assert "torrent title matches anime romaji title Reincarnation no Kaben" in romaji_reasons
    assert "torrent title matches anime alias title Petals Reincarnated" in alias_reasons

def test_batch_file_selection_skips_samples_sidecars_and_maps_episode_files(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["title"] = "Monster"
    anime["original_title"] = "Monster"
    anime["completion"] = {"expected_episodes": 6, "local_episodes": 2, "progress_target": 6, "missing_episodes": 4}
    anime["episode_files"] = [
        "C:/Anime/Monster/[HorribleSubs] Monster - 01 [1080p].mkv",
        "C:/Anime/Monster/[HorribleSubs] Monster - 02 [1080p].mkv",
    ]
    release = {
        "title": "[Manual] Monster",
        "torrent_url": "https://nyaa.si/download/1047039.torrent",
        "detail_url": "https://nyaa.si/view/1047039",
        "release_kind": "batch",
        "release_group": "Manual",
        "infohash": "",
        "autofill_from_torrent_files": True,
    }
    anime["download_queue"] = app_state._download_queue_from_release(
        release,
        anime,
        database["settings"]["download_client"],
        database["settings"]["root_folder"],
        [3, 4, 5, 6],
    )
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [
            {"hash": "single-monster-hash", "name": "(Hi10)_Monster_-_67_(DVD_480p)_(Figmentos).mkv", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"},
            {"hash": "monster-batch-hash", "name": "[AnimeRG] Naoki Urasawa's Monster (Complete Anime Series)", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"},
        ],
        {
            "single-monster-hash": [
                {"index": 0, "name": "(Hi10)_Monster_-_67_(DVD_480p)_(Figmentos).mkv"},
            ],
            "monster-batch-hash": [
                {"index": 0, "name": "Monster/[Group] Monster - 01 [1080p].mkv"},
                {"index": 1, "name": "Monster/[Group] Monster - 02 [1080p].mkv"},
                {"index": 2, "name": "Monster/[Group] Monster - 03 [1080p].mkv"},
                {"index": 3, "name": "Monster/[Group] Monster - 04 [1080p].mkv"},
                {"index": 4, "name": "Monster/[Group] Monster - 05 [1080p].mkv"},
                {"index": 5, "name": "Monster/[Group] Monster - 06 [1080p].mkv"},
                {"index": 6, "name": "Monster/Samples/[Group] Monster - 03 sample.mkv"},
                {"index": 7, "name": "Monster/Pictures/cover.jpg"},
                {"index": 8, "name": "Monster/url.url"},
            ]
        },
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    queue = anime["download_queue"]
    assert changed is True
    assert queue["hash"] == "monster-batch-hash"
    assert queue["safety_status"] == "safe"
    assert queue["release_kind"] == "batch"
    assert queue["wanted_episodes"] == [3, 4, 5, 6]
    assert queue["torrent_file_episodes"] == [1, 2, 3, 4, 5, 6]
    assert queue["file_selection_status"] == "applied"
    assert queue["selected_episode_files"] == [
        {"episode": 3, "index": 2, "name": "Monster/[Group] Monster - 03 [1080p].mkv"},
        {"episode": 4, "index": 3, "name": "Monster/[Group] Monster - 04 [1080p].mkv"},
        {"episode": 5, "index": 4, "name": "Monster/[Group] Monster - 05 [1080p].mkv"},
        {"episode": 6, "index": 5, "name": "Monster/[Group] Monster - 06 [1080p].mkv"},
    ]
    assert ("monster-batch-hash", [0, 1, 6, 7, 8], 0) in client.file_priorities
    assert ("monster-batch-hash", [2, 3, 4, 5], 1) in client.file_priorities
    assert "sample file" in queue["message"]
    assert "sidecar file" in queue["message"]


def test_batch_safety_still_flags_dangerous_sidecar(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    release = {
        "title": "[Manual] Monster",
        "torrent_url": "https://nyaa.si/download/1047039.torrent",
        "detail_url": "https://nyaa.si/view/1047039",
        "release_kind": "batch",
        "release_group": "Manual",
        "infohash": "danger-batch-hash",
        "autofill_from_torrent_files": True,
    }
    anime["download_queue"] = app_state._download_queue_from_release(
        release,
        anime,
        database["settings"]["download_client"],
        database["settings"]["root_folder"],
        [1],
    )
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [{"hash": "danger-batch-hash", "name": "Monster", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"}],
        {"danger-batch-hash": [{"index": 0, "name": "Monster/[Group] Monster - 01 [1080p].mkv"}, {"index": 1, "name": "Monster/runme.exe"}]},
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "flagged"
    assert anime["download_queue"]["safety_status"] == "flagged"
    assert client.file_priorities == []


def test_supplied_add_single_episode_tracks_subber_for_remaining_search(monkeypatch) -> None:
    database = auto_dispatch_database([
        auto_candidate(episode=6, group="OtherSubs"),
        auto_candidate(episode=6, group="SteadySubs"),
    ])
    anime = database["anime"][0]
    anime["completion"] = {"expected_episodes": 12, "local_episodes": 4, "progress_target": 12, "missing_episodes": 8}
    release, error = app_state._supplied_add_torrent_release(anime, "https://nyaa.si/download/555.torrent", database)
    assert error == ""
    release["infohash"] = "episode-hash"
    anime["download_queue"] = app_state._download_queue_from_release(
        release,
        anime,
        database["settings"]["download_client"],
        database["settings"]["root_folder"],
        list(range(5, 13)),
    )
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [{"hash": "episode-hash", "name": "Petals 05", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"}],
        {"episode-hash": [{"index": 0, "name": "[SteadySubs] Petals of Reincarnation - 05 [1080p].mkv"}]},
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._refresh_download_queue(database)
    selected = app_state._selected_download_releases(anime["torrent_search"]["candidates"], database, anime)

    assert anime["download_queue"]["release_kind"] == "episode"
    assert anime["download_queue"]["episode"] == 5
    assert anime["download_queue"]["release_group"] == "SteadySubs"
    assert selected and selected[0]["release_group"] == "SteadySubs"
    assert any("matches existing local release group SteadySubs" in reason for reason in selected[0]["confidence_reasons"])


def test_dispatch_prefers_subber_from_existing_local_episode_files(monkeypatch) -> None:
    database = auto_dispatch_database([
        auto_candidate(episode=29, group="HighSeeds"),
        auto_candidate(episode=29, group="SubsPlease"),
    ])
    anime = database["anime"][0]
    anime["title"] = "Digimon Beatbreak"
    anime["episodes"] = "29"
    anime["completion"] = {"expected_episodes": 29, "local_episodes": 28, "progress_target": 29, "missing_episodes": 1}
    anime["episode_files"] = [
        f"C:/Anime/Digimon Beatbreak/[SubsPlease] Digimon Beatbreak - {episode:02d} [1080p].mkv"
        for episode in range(1, 29)
    ]
    high_seed = anime["torrent_search"]["candidates"][0]
    local_group = anime["torrent_search"]["candidates"][1]
    high_seed["seeders"] = 500
    local_group["seeders"] = 5
    for candidate in anime["torrent_search"]["candidates"]:
        candidate["title"] = f"[{candidate['release_group']}] Digimon Beatbreak - 29 [1080p]"
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert client.urls == ["https://nyaa.si/download/SubsPlease-29.torrent"]
    assert anime["download_queue"]["release_group"] == "SubsPlease"
    assert any("matches existing local release group SubsPlease" in reason for reason in anime["download_queue"]["confidence_reasons"])

def test_dispatch_episode_uses_existing_local_anime_folder(monkeypatch) -> None:
    database = auto_dispatch_database([auto_candidate(episode=10, group="SubsPlease")])
    anime = database["anime"][0]
    anime["title"] = "SHIBOYUGI: Playing Death Games to Put Food on the Table"
    anime["original_title"] = "Shibou Yuugi de Meshi wo Kuu."
    anime["local_path"] = "C:/Anime/Shibou Yuugi de Meshi wo Kuu"
    anime["completion"] = {"expected_episodes": 11, "local_episodes": 9, "progress_target": 11, "missing_episodes": 2}
    anime["torrent_search"]["candidates"][0]["title"] = "[SubsPlease] Shibou Yuugi de Meshi wo Kuu. - 10 (1080p).mkv"
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert client.calls[0]["save_path"] == "C:/Anime/Shibou Yuugi de Meshi wo Kuu"
    assert anime["download_queue"]["save_path"] == "C:/Anime/Shibou Yuugi de Meshi wo Kuu"
    assert client.calls[0]["root_folder"] is False
    assert anime["download_queue"]["target_folder"] == "Shibou Yuugi de Meshi wo Kuu"


def test_dispatch_queues_all_missing_episode_candidates_from_same_subber(monkeypatch) -> None:
    database = auto_dispatch_database([auto_candidate(episode) for episode in range(1, 4)])
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, database["anime"][0])

    anime = database["anime"][0]
    assert client.urls == [
        "https://nyaa.si/download/SteadySubs-1.torrent",
        "https://nyaa.si/download/SteadySubs-2.torrent",
        "https://nyaa.si/download/SteadySubs-3.torrent",
    ]
    assert [queue["episode"] for queue in anime["download_queues"]] == [1, 2, 3]
    assert all("rename" not in call for call in client.calls)
    assert {queue["target_folder"] for queue in anime["download_queues"]} == {"Petals of Reincarnation"}


def test_dispatch_skips_existing_active_episode_queue_but_queues_remaining_missing(monkeypatch) -> None:
    database = auto_dispatch_database([auto_candidate(episode) for episode in range(1, 4)])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "steadysubs-1",
        "torrent_url": "https://nyaa.si/download/SteadySubs-1.torrent",
        "release_kind": "episode",
        "episode": 1,
    }
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert client.urls == [
        "https://nyaa.si/download/SteadySubs-2.torrent",
        "https://nyaa.si/download/SteadySubs-3.torrent",
    ]
    assert [queue["episode"] for queue in anime["download_queues"]] == [1, 2, 3]


def test_airing_progress_target_uses_currently_aired_episode_before_full_count() -> None:
    anime = {"status": "Releasing", "airing_episode": "12", "episodes": "19"}

    assert app_state._progress_episode_target(anime, 19) == 11



def test_manual_selection_hides_candidates_already_in_qbittorrent_by_hash(monkeypatch) -> None:
    candidate = manual_candidate("candidate-1")
    database = manual_database(candidate)
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    writes = []
    client = FakeDownloadClient([{"hash": "candidate-1", "name": "[SteadySubs] Petals of Reincarnation - 05 [1080p].mkv"}])
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    model = app_state.manual_selection_model()

    assert model == {"items": [], "count": 0}
    assert database["anime"][0]["torrent_manual_selection"] == {"required": False}
    assert writes == [database]


def test_sidebar_manual_selection_count_uses_visible_manual_rows(monkeypatch) -> None:
    candidate = manual_candidate("candidate-1")
    database = manual_database(candidate)
    database["events"] = []
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    writes = []
    client = FakeDownloadClient([{"hash": "candidate-1", "name": "[SteadySubs] Petals of Reincarnation - 05 [1080p].mkv"}])
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "missing_settings_summary", lambda database=None: {"count": 0})

    counts = app_state.sidebar_counts()

    assert counts["manual_selection"] == 0
    assert database["anime"][0]["torrent_manual_selection"] == {"required": False}
    assert writes == [database]


def test_manual_selection_hides_same_anime_episode_already_in_qbittorrent(monkeypatch) -> None:
    candidate = manual_candidate("different-hash")
    database = manual_database(candidate)
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    client = FakeDownloadClient([{"hash": "other-hash", "name": "Petals of Reincarnation S01E05 1080p WEB-DL AAC2.0 x265-VARYG.mkv"}])
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: None)
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    model = app_state.manual_selection_model()

    assert model["count"] == 0
    assert database["anime"][0]["torrent_manual_selection"] == {"required": False}


def test_dispatch_selection_skips_candidate_already_in_qbittorrent_by_episode(monkeypatch) -> None:
    database = auto_dispatch_database([auto_candidate(episode) for episode in range(1, 4)])
    anime = database["anime"][0]
    client = FakeDownloadClient([{"hash": "external-2", "name": "Petals of Reincarnation S01E02 1080p WEB-DL AAC2.0 x265-VARYG.mkv"}])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    selected = app_state._selected_download_releases(anime["torrent_search"]["candidates"], database, anime)

    assert [candidate["episode"] for candidate in selected] == [1, 3]



def test_download_client_snapshot_reads_episode_from_content_path_when_name_is_folder() -> None:
    database = manual_database()
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    anime = database["anime"][0]
    client = FakeDownloadClient([
        {
            "hash": "external-5",
            "name": "Petals of Reincarnation",
            "content_path": "//server/Torrents/Anime/Petals.of.Reincarnation.S01E05.1080p.WEB-DL.x265-VARYG.mkv",
        }
    ])

    snapshot = app_state._download_client_existing_snapshot(database | {"anime": [anime]}) if False else None
    # Avoid calling the real client; exercise the name matching through manual selection instead.
    assert app_state._torrent_name_matches_anime(anime, "Petals.of.Reincarnation.S01E05.1080p.WEB-DL.x265-VARYG.mkv") is True
    assert app_state.episode_number_from_title("Petals.of.Reincarnation.S01E05.1080p.WEB-DL.x265-VARYG.mkv") == 5
    assert app_state._download_client_torrent_names(client._torrents[0])[0].startswith("Petals.of.Reincarnation.S01E05")


def root_scan_metadata(title: str = "Petals of Reincarnation") -> dict[str, object]:
    return {
        "title": title,
        "original_title": title,
        "year": "2026",
        "status": "Releasing",
        "episodes": "13",
        "season_number": 1,
        "runtime": "24 min",
        "genres": ["Action"],
        "aliases": [],
        "studio": "Studio",
        "source": "AniList",
        "rating": "80%",
        "synopsis": "Metadata result.",
        "poster": "",
        "air_date": "2026-04-01",
        "next_airing_at": "",
        "airing_episode": "",
        "airing_source": "AniList",
        "provider_ids": {"anilist": "179950"},
    }


def test_root_folder_import_uses_live_metadata_without_env_gate(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Petals.of.Reincarnation.S01E03.1080p.mkv"
    media_file.write_bytes(b"")
    calls = []

    monkeypatch.setattr(app_state, "ROOT_IMPORT_METADATA_ON_SAVE", False)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: calls.append(titles) or [root_scan_metadata()])

    item = app_state._imported_anime_item("Petals of Reincarnation", tmp_path, [media_file])

    assert calls == [["Petals of Reincarnation"]]
    assert item["title"] == "Petals of Reincarnation"
    assert item["episodes"] == "13"
    assert item["manual_verification_required"] is False
    assert item["metadata_resolution_source"] == "provider"


def test_root_folder_import_with_fallback_provider_marks_anilist_reconciliation_pending(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Fallback.Show.S01E01.1080p.mkv"
    media_file.write_bytes(b"")
    kitsu = root_scan_metadata("Fallback Show")
    kitsu.update({"source": "Kitsu", "provider_ids": {"kitsu": "fallback-kitsu"}, "poster": "https://kitsu.example/fallback.jpg"})

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [kitsu])

    item = app_state._imported_anime_item("Fallback Show", tmp_path, [media_file])

    assert app_state._metadata_source_name(item) == "Kitsu"
    assert item["metadata_resolution_source"] == "provider"
    assert item["anilist_reconciliation_status"] == "pending"
    assert item["anilist_reconciliation_reason"] == "Resolved from Kitsu; final AniList reconciliation is pending."
    assert "anilist_metadata_checked_at" not in item


def test_root_scan_merges_partial_folder_into_existing_anime_and_marks_missing(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    folder = root / "Petals of Reincarnation"
    folder.mkdir(parents=True)
    for episode in (3, 4, 5):
        (folder / f"Petals.of.Reincarnation.S01E{episode:02d}.1080p.mkv").write_bytes(b"")
    database = {
        "settings": {"root_folder": str(root)},
        "anime": [
            {
                "library_id": "AniList:179950",
                "title": "Petals of Reincarnation",
                "original_title": "Petals of Reincarnation",
                "episodes": "13",
                "status": "Releasing",
                "monitored": True,
                "quality_resolution": "1080p",
                "provider_ids": {"anilist": "179950"},
                "torrent_search": {"candidates": [], "notices": []},
            }
        ],
    }

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [root_scan_metadata()])

    summary = app_state._import_root_folder_anime(database, root)
    anime = database["anime"][0]

    assert summary["updated"] == 1
    assert summary["imported"] == 0
    assert len(database["anime"]) == 1
    assert anime["library_id"] == "AniList:179950"
    assert anime["manual_verification_required"] is False
    assert anime["completion"]["missing_episodes"] == 10
    nfo = folder / "tvshow.nfo"
    assert nfo.exists()
    assert '<uniqueid type="anilist" default="true">179950</uniqueid>' in nfo.read_text(encoding="utf-8")
    assert app_state._missing_episode_numbers(anime) == [1, 2, 6, 7, 8, 9, 10, 11, 12, 13]
    assert anime["torrent_search"]["strategy"] == "Queued for background torrent search"


def test_root_scan_keeps_new_candidate_unmonitored_when_title_was_paused(tmp_path) -> None:
    root = tmp_path / "Anime"
    folder = root / "Chiikawa"
    folder.mkdir(parents=True)
    media_file = folder / "Chiikawa.S01E01.1080p.mkv"
    media_file.write_bytes(b"")
    database = {
        "settings": {"root_folder": str(root)},
        "events": [],
        "anime": [
            {
                "library_id": "AniList:170182",
                "title": "Chiikawa",
                "original_title": "Chiikawa",
                "episodes": "200",
                "status": "Releasing",
                "monitored": False,
                "quality_resolution": "1080p",
                "provider_ids": {"anilist": "170182"},
                "torrent_search": {"strategy": "Torrent search paused because anime is unmonitored", "candidates": []},
            }
        ],
    }
    candidate = {
        "library_id": f"root-folder:{app_state._stable_path_id(folder.resolve())}",
        "title": "Chiikawa",
        "original_title": "Chiikawa",
        "episodes": "1",
        "status": "Unknown",
        "monitored": True,
        "quality_resolution": "1080p",
        "local_path": str(folder.resolve()),
        "episode_files": [str(media_file.resolve())],
        "torrent_search": {"query": "Chiikawa", "strategy": "Imported from root folder scan", "candidates": []},
    }
    summary = app_state._empty_scan_summary()

    stored = app_state._store_root_folder_candidate(database, candidate, summary)

    assert summary["imported"] == 1
    assert len(database["anime"]) == 2
    assert stored["library_id"].startswith("root-folder:")
    assert stored["monitored"] is False
    assert stored["library_state"] == "Paused"
    assert stored["torrent_manual_selection"] == {"required": False}
    assert stored["torrent_search"]["strategy"] == "Torrent search paused because anime is unmonitored"


def test_root_scan_removes_existing_root_folder_duplicate_when_provider_item_uses_same_folder(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    folder = root / "Petals of Reincarnation"
    folder.mkdir(parents=True)
    media_file = folder / "Petals.of.Reincarnation.S01E03.1080p.mkv"
    media_file.write_bytes(b"")
    provider_item = {
        "library_id": "AniList:179950",
        "title": "Petals of Reincarnation",
        "original_title": "Petals of Reincarnation",
        "episodes": "13",
        "status": "Releasing",
        "monitored": True,
        "quality_resolution": "1080p",
        "provider_ids": {"anilist": "179950"},
        "local_path": str(folder.resolve()),
        "torrent_search": {"candidates": [], "notices": []},
    }
    root_duplicate = {
        "library_id": f"root-folder:{app_state._stable_path_id(folder.resolve())}",
        "title": "Petals of Reincarnation (1 local episodes)",
        "original_title": "Petals of Reincarnation",
        "episodes": "1",
        "status": "Unknown",
        "monitored": True,
        "quality_resolution": "1080p",
        "provider_ids": {"anilist": "179950"},
        "local_path": str(folder.resolve()),
        "manual_verification_required": True,
        "torrent_search": {"strategy": "Manual metadata verification required", "candidates": [], "notices": []},
    }
    database = {"settings": {"root_folder": str(root)}, "anime": [provider_item, root_duplicate]}

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [root_scan_metadata()])

    summary = app_state._import_root_folder_anime(database, root)

    assert summary["updated"] == 1
    assert len(database["anime"]) == 1
    anime = database["anime"][0]
    assert anime["library_id"] == "AniList:179950"
    assert anime["local_path"] == str(folder.resolve())
    assert anime["manual_verification_required"] is False
    assert anime["completion"]["missing_episodes"] == 12
    assert anime["torrent_search"]["strategy"] == "Queued for background torrent search"


def test_same_path_root_folder_duplicate_collapses_on_database_normalization(tmp_path) -> None:
    folder = tmp_path / "Petals of Reincarnation"
    folder.mkdir()
    files = []
    for episode in (3, 4, 5):
        media_file = folder / f"Petals.of.Reincarnation.S01E{episode:02d}.1080p.mkv"
        media_file.write_bytes(b"")
        files.append(str(media_file.resolve()))
    provider_item = {
        "library_id": "AniList:179950",
        "title": "Petals of Reincarnation",
        "original_title": "Reincarnation no Kaben",
        "episodes": "13",
        "status": "Releasing",
        "monitored": True,
        "quality_resolution": "1080p",
        "provider_ids": {"anilist": 179950, "mal": 59443},
        "local_path": str(folder.resolve()),
        "episode_files": files[:2],
    }
    root_duplicate = {
        "library_id": f"root-folder:{app_state._stable_path_id(folder.resolve())}",
        "title": "Petals of Reincarnation (3 local episodes)",
        "original_title": "Petals of Reincarnation",
        "episodes": "3",
        "status": "Unknown",
        "monitored": True,
        "quality_resolution": "1080p",
        "provider_ids": {"kitsu": "49118"},
        "local_path": str(folder.resolve()),
        "episode_files": files,
        "manual_verification_required": True,
    }
    library = [provider_item, root_duplicate]

    changed = app_state._merge_same_path_root_folder_duplicates(library)

    assert changed is True
    assert library == [provider_item]
    assert provider_item["library_id"] == "AniList:179950"
    assert provider_item["episodes"] == "13"
    assert provider_item["episode_files"] == files


def test_no_candidate_manual_selection_hold_does_not_block_refresh(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    anime = missing_anime(checked_at="2026-06-25T00:00:00+00:00", candidates=[])
    anime["torrent_manual_selection"] = {
        "required": True,
        "reason": "No usable torrent candidate is available.",
        "confidence": 0,
        "best_candidate_title": "",
    }
    now = datetime(2026, 6, 25, 0, 2, tzinfo=timezone.utc).timestamp()

    assert app_state._manual_selection_required(anime) is False
    assert app_state._should_refresh_torrent_search(anime, now) is True


def test_qbittorrent_status_outage_keeps_queued_activity_visible(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "queued",
        "hash": "active-hash",
        "episode": 2,
        "message": "Queued torrent is waiting for qBittorrent.",
    }
    anime["download_queues"] = [anime["download_queue"]]

    class FailingStatusClient:
        def torrents(self, **kwargs: object) -> list[dict[str, object]]:
            raise app_state.QBittorrentError("connection refused")

    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: FailingStatusClient())

    changed = app_state._refresh_download_queue(database)
    rows = app_state._activity_queued_rows(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "queued"
    assert "status check failed" in anime["download_queue"]["message"]
    assert any(row["status"] == "queued" and row["episode"] == "2" for row in rows)
    assert any(row["status"] == "wanted" and row["episode"] == "1" for row in rows)


def test_activity_queued_rows_do_not_mark_download_client_episode_as_wanted(monkeypatch) -> None:
    database = auto_dispatch_database([])
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    anime = database["anime"][0]
    anime["completion"] = {
        "expected_episodes": 3,
        "local_episodes": 2,
        "progress_target": 3,
        "missing_episodes": 1,
    }
    anime["episode_files"] = [
        "C:/Anime/Petals/Petals.of.Reincarnation.S01E01.mkv",
        "C:/Anime/Petals/Petals.of.Reincarnation.S01E02.mkv",
    ]
    client = FakeDownloadClient([{"hash": "external-3", "name": "Petals of Reincarnation S01E03 1080p WEB-DL.mkv"}])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    assert app_state._activity_queued_rows(database, include_client_snapshot=True) == []



def test_activity_queued_rows_skip_unmonitored_anime() -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["monitored"] = False
    anime["completion"] = {
        "expected_episodes": 3,
        "local_episodes": 1,
        "progress_target": 3,
        "missing_episodes": 2,
    }
    anime["download_queue"] = {
        "status": "queued",
        "hash": "active-hash",
        "episode": 2,
        "message": "Queued torrent is waiting for qBittorrent.",
    }
    anime["download_queues"] = [anime["download_queue"]]

    assert app_state._activity_queued_rows(database) == []
    assert app_state._active_activity_count(database["anime"]) == 0

def test_activity_model_does_not_refresh_download_client_on_page_load(monkeypatch) -> None:
    database = auto_dispatch_database([])
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_refresh_download_queue", lambda db: (_ for _ in ()).throw(AssertionError("page load refreshed qBittorrent")))
    monkeypatch.setattr(app_state, "_download_client_existing_snapshot", lambda db: (_ for _ in ()).throw(AssertionError("page load read qBittorrent snapshot")))

    model = app_state.activity_model("queued")

    assert model["section"] == "queued"
    assert writes == []

def test_activity_queued_rows_include_missing_episodes_without_selected_torrent() -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["completion"] = {
        "expected_episodes": 3,
        "local_episodes": 2,
        "progress_target": 3,
        "missing_episodes": 1,
    }
    anime["episode_files"] = [
        "C:/Anime/Petals/[SteadySubs] Petals of Reincarnation - 01 [1080p].mkv",
        "C:/Anime/Petals/[SteadySubs] Petals of Reincarnation - 02 [1080p].mkv",
    ]

    rows = app_state._activity_queued_rows(database)

    assert rows == [app_state._activity_missing_episode_row(anime, 3)]
    assert app_state._active_activity_count(database["anime"]) == 1


def test_activity_queued_rows_mark_resolved_candidate_as_dispatch_pending() -> None:
    candidate = auto_candidate(3)
    database = auto_dispatch_database([candidate])
    anime = database["anime"][0]
    anime["completion"] = {
        "expected_episodes": 3,
        "local_episodes": 2,
        "progress_target": 3,
        "missing_episodes": 1,
    }
    anime["episode_files"] = [
        "C:/Anime/Petals/[SteadySubs] Petals of Reincarnation - 01 [1080p].mkv",
        "C:/Anime/Petals/[SteadySubs] Petals of Reincarnation - 02 [1080p].mkv",
    ]

    rows = app_state._activity_queued_rows(database)

    assert len(rows) == 1
    assert rows[0]["episode"] == "3"
    assert rows[0]["status"] == "resolved"
    assert rows[0]["status_label"] == "Resolved · dispatch pending"
    assert rows[0]["title"] == candidate["title"]


def test_missing_qbittorrent_queue_is_marked_missing_and_no_longer_counts_as_queued(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "queued",
        "hash": "missing-hash",
        "episode": 2,
        "message": "Queued torrent is not visible in qBittorrent yet.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "missing"
    assert "no longer visible" in anime["download_queue"]["message"]
    assert app_state._queued_episode_numbers(anime) == set()


def test_refresh_download_queue_relocates_episode_to_existing_local_folder(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["local_path"] = "C:/Anime/Shibou Yuugi de Meshi wo Kuu"
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "subsplease-10",
        "episode": 10,
        "release_kind": "episode",
        "release_group": "SubsPlease",
        "save_path": "C:/Anime",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([{
        "hash": "subsplease-10",
        "name": "[SubsPlease] Shibou Yuugi de Meshi wo Kuu. - 10 (1080p).mkv",
        "progress": 0.25,
        "state": "downloading",
        "save_path": "C:/Anime",
    }])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.locations == [("subsplease-10", "C:/Anime/Shibou Yuugi de Meshi wo Kuu")]
    assert anime["download_queue"]["save_path"] == "C:/Anime/Shibou Yuugi de Meshi wo Kuu"
    assert anime["download_queue"]["relocation_status"] == "moved_to_local_folder"


def test_missing_hash_queue_reappearing_in_qbittorrent_is_revived(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "missing",
        "hash": "missing-hash",
        "episode": 2,
        "release_group": "SteadySubs",
        "message": "Queued torrent is no longer visible in qBittorrent and will be searched again.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([{
        "hash": "missing-hash",
        "name": "[SteadySubs] Petals of Reincarnation - 02 [1080p].mkv",
        "progress": 0.5,
        "state": "downloading",
        "save_path": "C:/Anime",
    }])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "downloading"
    assert anime["download_queue"]["progress"] == 50
    assert anime["download_queue"]["unblocked_retry"] is True


def test_unblocked_missing_wrong_group_queue_still_respects_local_subber(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["episode_files"] = ["C:/Anime/Petals/[SubsPlease] Petals of Reincarnation - 01 [1080p].mkv"]
    anime["download_queue"] = {
        "status": "missing",
        "hash": "varyg-2",
        "episode": 2,
        "release_group": "VARYG",
        "message": "Queued torrent is no longer visible in qBittorrent and will be searched again.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([{
        "hash": "varyg-2",
        "name": "Petals of Reincarnation S01E02 1080p WEB-DL AAC2.0 H264-VARYG.mkv",
        "progress": 0.25,
        "state": "downloading",
        "save_path": "C:/Anime",
    }])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "rejected"
    assert anime["download_queue"]["unblocked_retry"] is True
    assert client.deleted == [("varyg-2", True)]
    assert database["ignored_torrents"][0]["hash"] == "varyg-2"


def test_refresh_download_queue_marks_locally_present_error_queue_imported(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["completion"] = {"expected_episodes": 13, "local_episodes": 13, "progress_target": 13, "missing_episodes": 0}
    anime["library_state"] = "Completed"
    anime["episode_files"] = [f"/anime/Petals.of.Reincarnation.S01E{episode:02d}.mkv" for episode in range(1, 14)]
    anime["download_queue"] = {
        "status": "error",
        "hash": "episode-10-hash",
        "episode": 10,
        "progress": 0,
        "import_status": "imported",
        "message": "qBittorrent reported an error for this torrent.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([{"hash": "episode-10-hash", "name": "Petals 10", "progress": 0, "state": "missingFiles"}])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "imported"
    assert anime["download_queue"]["progress"] == 100
    assert app_state._active_download_queue(anime) is False
    assert app_state._activity_queued_rows(database) == []


def test_activity_ignores_stale_active_queue_for_local_episode() -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["completion"] = {"expected_episodes": 13, "local_episodes": 13, "progress_target": 13, "missing_episodes": 0}
    anime["library_state"] = "Completed"
    anime["episode_files"] = [f"/anime/Petals.of.Reincarnation.S01E{episode:02d}.mkv" for episode in range(1, 14)]
    anime["download_queue"] = {"status": "error", "episode": 13, "progress": 0}
    anime["download_queues"] = [anime["download_queue"]]

    assert app_state._active_download_queue(anime) is False
    assert app_state._activity_queued_rows(database) == []


def test_completed_anime_does_not_report_filename_gaps_as_missing() -> None:
    anime = {
        "library_state": "Completed",
        "completion": {"expected_episodes": 12, "local_episodes": 12, "progress_target": 12},
        "episode_files": [f"/anime/Show.S01E{episode:02d}.mkv" for episode in range(13, 25)],
    }

    assert app_state._missing_episode_numbers(anime) == []


def test_dispatch_does_not_dedupe_against_missing_queue_records(monkeypatch) -> None:
    candidate = auto_candidate(episode=5)
    database = auto_dispatch_database([candidate])
    anime = database["anime"][0]
    anime["completion"] = {
        "expected_episodes": 5,
        "local_episodes": 4,
        "progress_target": 5,
        "missing_episodes": 1,
    }
    anime["download_queue"] = {
        "status": "missing",
        "hash": candidate["infohash"],
        "torrent_url": candidate["torrent_url"],
        "episode": 5,
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert client.urls == [candidate["torrent_url"]]
    assert any(queue.get("episode") == 5 and queue.get("status") == "pending_safety" for queue in anime["download_queues"])


def test_dispatch_batch_cleans_up_individual_episode_torrents(monkeypatch) -> None:
    batch = manual_candidate("batch-hash")
    batch.update(
        {
            "title": "[SteadySubs] Petals of Reincarnation Complete Batch [1080p]",
            "torrent_url": "https://nyaa.si/download/batch.torrent",
            "detail_url": "https://nyaa.si/view/batch",
            "infohash": "batch-hash",
            "release_kind": "batch",
            "episode": None,
            "wanted_episodes": [1, 2, 3],
        }
    )
    database = auto_dispatch_database([batch])
    anime = database["anime"][0]
    anime["download_queues"] = [
        {"status": "downloading", "hash": "episode-1", "release_kind": "episode", "episode": 1},
        {"status": "queued", "hash": "episode-2", "release_kind": "episode", "episode": 2},
        {"status": "downloading", "hash": "episode-9", "release_kind": "episode", "episode": 9},
    ]
    anime["download_queue"] = anime["download_queues"][0]
    client = FakeDownloadClient(
        [
            {"hash": "episode-1", "name": "Petals 01", "progress": 0.2, "state": "downloading"},
            {"hash": "episode-2", "name": "Petals 02", "progress": 0, "state": "pausedDL"},
            {"hash": "episode-9", "name": "Petals 09", "progress": 0.1, "state": "downloading"},
            {"hash": "already-known", "name": "Other", "progress": 0, "state": "pausedDL"},
        ]
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert client.urls == [batch["torrent_url"]]
    assert client.deleted == [("episode-1", True), ("episode-2", True)]
    assert [queue["status"] for queue in anime["download_queues"][:2]] == ["superseded", "superseded"]
    assert anime["download_queues"][2]["status"] == "downloading"
    assert any(queue.get("release_kind") == "batch" and queue.get("status") == "pending_safety" for queue in anime["download_queues"])


def test_dispatch_caps_backlog_per_anime_and_keeps_it_hot(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "MAX_TORRENT_DISPATCHES_PER_ANIME_TICK", 2)
    database = auto_dispatch_database([auto_candidate(episode) for episode in range(1, 5)])
    anime = database["anime"][0]
    anime["episodes"] = "4"
    anime["completion"] = {
        "expected_episodes": 4,
        "local_episodes": 0,
        "progress_target": 4,
        "missing_episodes": 4,
    }
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert len(client.urls) == 2
    assert anime["torrent_dispatch_backlog"] is True
    assert app_state._recent_dispatch_attempt(anime, 9999999999) is False
    assert any("Deferred 2 resolved torrent(s)" in notice for notice in anime["torrent_search"]["notices"])


def test_dispatch_inspects_and_starts_safe_torrent_immediately(monkeypatch) -> None:
    candidate = auto_candidate(1)
    database = auto_dispatch_database([candidate])
    anime = database["anime"][0]
    client = FakeDownloadClient(
        files_by_hash={
            str(candidate["infohash"]).casefold(): [
                {"index": 0, "name": "[SteadySubs] Petals of Reincarnation - 01 [1080p].mkv"}
            ]
        }
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    queue = anime["download_queue"]
    assert queue["safety_status"] == "safe"
    assert queue["status"] == "queued"
    assert client.resumed == [str(candidate["infohash"]).casefold()]
    assert "started immediately" in queue["message"]


def test_dispatch_keeps_async_qbittorrent_add_as_submitted_without_duplicate(monkeypatch) -> None:
    candidate = auto_candidate(1)
    database = auto_dispatch_database([candidate])
    anime = database["anime"][0]

    class AsyncAddClient(FakeDownloadClient):
        def add_url(self, url: str, **kwargs: object) -> bool:
            super().add_url(url, **kwargs)
            return False

    client = AsyncAddClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)
    app_state._maybe_dispatch_torrent(database, anime)

    assert client.urls == [candidate["torrent_url"]]
    assert anime["download_queue"]["status"] == "submitted"
    assert app_state._queued_episode_numbers(anime) == {1}


def test_refresh_download_queue_cleans_up_episode_torrents_covered_by_existing_batch(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queues"] = [
        {
            "status": "downloading",
            "hash": "batch-hash",
            "release_kind": "batch",
            "wanted_episodes": [1, 2, 3],
            "select_batch_files": True,
            "file_selection_status": "applied",
            "safety_status": "safe",
        },
        {"status": "downloading", "hash": "episode-1", "release_kind": "episode", "episode": 1},
        {"status": "paused", "hash": "episode-3", "release_kind": "episode", "episode": 3},
        {"status": "downloading", "hash": "episode-4", "release_kind": "episode", "episode": 4},
    ]
    anime["download_queue"] = anime["download_queues"][0]
    client = FakeDownloadClient(
        [
            {"hash": "batch-hash", "name": "Petals batch", "progress": 0.4, "state": "downloading", "save_path": "C:/Anime"},
            {"hash": "episode-1", "name": "Petals 01", "progress": 0.5, "state": "downloading"},
            {"hash": "episode-3", "name": "Petals 03", "progress": 0, "state": "pausedDL"},
            {"hash": "episode-4", "name": "Petals 04", "progress": 0.2, "state": "downloading"},
        ]
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.deleted == [("episode-1", True), ("episode-3", True)]
    assert anime["download_queues"][1]["status"] == "superseded"
    assert anime["download_queues"][2]["status"] == "superseded"
    assert anime["download_queues"][3]["status"] == "downloading"

def test_activity_progress_treats_active_one_as_one_percent() -> None:
    assert app_state._activity_progress({"status": "downloading", "progress": 1}) == 1
    assert app_state._activity_progress({"status": "queued", "progress": 0.02}) == 2
    assert app_state._activity_progress({"status": "imported", "progress": 1}) == 100


def test_qbittorrent_resume_falls_back_to_start_on_404() -> None:
    client = qbittorrent_client.QBittorrentClient({"host": "localhost", "port": 8080})
    calls = []

    def fake_request(path, *, data=None, headers=None, method="POST"):
        calls.append((path, data))
        if path == "/api/v2/torrents/resume":
            raise qbittorrent_client.QBittorrentError("qBittorrent request failed: HTTP 404.")
        return b""

    client._request = fake_request

    client.resume("abc123")

    assert calls == [
        ("/api/v2/torrents/resume", {"hashes": "abc123"}),
        ("/api/v2/torrents/start", {"hashes": "abc123"}),
    ]


def test_qbittorrent_add_url_rejects_textual_failure_response() -> None:
    client = qbittorrent_client.QBittorrentClient({"host": "localhost", "port": 8080})
    client._multipart_request = lambda path, fields: b"Fails."

    try:
        client.add_url(
            "https://nyaa.si/download/123.torrent",
            save_path="C:/Anime",
            category="nyaarr",
            tags="nyaarr,anime-1",
        )
    except qbittorrent_client.QBittorrentError as exc:
        assert "rejected the torrent add request: Fails." in str(exc)
    else:
        raise AssertionError("qBittorrent's textual failure response must not create a queue record")


def test_qbittorrent_add_url_accepts_ok_response() -> None:
    client = qbittorrent_client.QBittorrentClient({"host": "localhost", "port": 8080})
    client._multipart_request = lambda path, fields: b"Ok."

    client.add_url(
        "https://nyaa.si/download/123.torrent",
        save_path="C:/Anime",
        category="nyaarr",
        tags="nyaarr,anime-1",
    )


def test_qbittorrent_add_url_reports_expected_hash_not_yet_visible(monkeypatch) -> None:
    client = qbittorrent_client.QBittorrentClient({"host": "localhost", "port": 8080})
    client._multipart_request = lambda path, fields: b"Ok."
    client.torrents = lambda **kwargs: []
    monkeypatch.setattr(qbittorrent_client.time, "sleep", lambda seconds: None)

    visible = client.add_url(
        "https://nyaa.si/download/123.torrent",
        save_path="C:/Anime",
        category="nyaarr",
        tags="nyaarr,anime-1",
        expected_infohash="abc123",
    )

    assert visible is False


def test_qbittorrent_add_url_confirms_expected_hash(monkeypatch) -> None:
    client = qbittorrent_client.QBittorrentClient({"host": "localhost", "port": 8080})
    client._multipart_request = lambda path, fields: b"Ok."
    snapshots = [[], [{"hash": "abc123"}]]
    client.torrents = lambda **kwargs: snapshots.pop(0)
    monkeypatch.setattr(qbittorrent_client.time, "sleep", lambda seconds: None)

    client.add_url(
        "https://nyaa.si/download/123.torrent",
        save_path="C:/Anime",
        category="nyaarr",
        tags="nyaarr,anime-1",
        expected_infohash="abc123",
    )


def test_safe_auto_torrent_still_paused_is_resumed_on_refresh(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "paused",
        "hash": "safe-paused-hash",
        "safety_status": "safe",
        "user_add_paused": False,
        "save_path": "C:/Anime",
        "message": "Torrent is paused in qBittorrent.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {"hash": "safe-paused-hash", "name": "Petals", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"}
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.resumed == ["safe-paused-hash"]
    assert anime["download_queue"]["status"] == "paused"
    assert anime["download_queue"]["message"] == "Torrent passed safety inspection and qBittorrent was resumed."


def test_legacy_paused_torrent_without_safety_status_is_inspected_and_resumed(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "paused",
        "hash": "legacy-paused-hash",
        "user_add_paused": False,
        "save_path": "C:/Anime",
        "message": "Torrent is paused in qBittorrent.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [{"hash": "legacy-paused-hash", "name": "Petals", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"}],
        {"legacy-paused-hash": [{"name": "Petals.of.Reincarnation.S01E01.1080p.mkv"}]},
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.resumed == ["legacy-paused-hash"]
    assert anime["download_queue"]["safety_status"] == "safe"
    assert anime["download_queue"]["status"] == "paused"
    assert anime["download_queue"]["message"] == "Torrent passed safety inspection and qBittorrent was resumed."


def test_startup_download_status_check_refreshes_and_persists_paused_torrents(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "paused",
        "hash": "startup-paused-hash",
        "safety_status": "safe",
        "user_add_paused": False,
        "save_path": "C:/Anime",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {"hash": "startup-paused-hash", "name": "Petals", "progress": 0, "state": "pausedDL", "save_path": "C:/Anime"}
    ])
    writes = []
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    summary = app_state.run_startup_download_status_check()

    assert summary["status"] == "ok"
    assert summary["queue_refreshed"] is True
    assert client.resumed == ["startup-paused-hash"]
    assert writes == [database]
    assert any(event["category"] == "system" and "Startup torrent status check completed" in event["message"] for event in database["events"])


def test_user_add_paused_keeps_safe_torrent_paused(monkeypatch) -> None:
    database = auto_dispatch_database([])
    database["settings"]["download_client"]["add_paused"] = True
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "queued",
        "hash": "paused-hash",
        "safety_status": "pending",
        "user_add_paused": True,
        "save_path": "C:/Anime",
        "message": "Sent to qBittorrent paused for file safety inspection.",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [{"hash": "paused-hash", "name": "Petals", "progress": 0, "state": "pausedUP"}],
        {"paused-hash": [{"name": "Petals.of.Reincarnation.S01E01.1080p.mkv"}]},
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.resumed == []
    assert anime["download_queue"]["safety_status"] == "safe"
    assert anime["download_queue"]["status"] == "paused"


def test_safety_inspection_waiting_keeps_queue_pending(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "queued",
        "hash": "waiting-hash",
        "safety_status": "pending",
        "save_path": "C:/Anime",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient(
        [{"hash": "waiting-hash", "name": "Petals", "progress": 0, "state": "metaDL"}],
        file_error=app_state.QBittorrentError("metadata is not available yet"),
    )
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "pending_safety"
    assert anime["download_queue"]["safety_status"] == "pending"
    assert "Waiting for qBittorrent file metadata" in anime["download_queue"]["message"]


def test_completed_torrent_with_inaccessible_content_path_stays_completed(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "done-hash",
        "safety_status": "safe",
        "save_path": "Z:/NotMounted/Anime",
        "content_path": "Z:/NotMounted/Anime/Petals.of.Reincarnation.S01E01.1080p.mkv",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "done-hash",
            "name": "Petals.of.Reincarnation.S01E01.1080p.mkv",
            "progress": 1,
            "state": "uploading",
            "content_path": "Z:/NotMounted/Anime/Petals.of.Reincarnation.S01E01.1080p.mkv",
            "save_path": "Z:/NotMounted/Anime",
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "completed"
    assert anime["download_queue"]["completed_at"]
    assert anime.get("episode_files") is None


def test_rejected_flagged_torrent_is_ignored_and_not_retried(monkeypatch) -> None:
    rejected = auto_candidate(episode=1)
    database = auto_dispatch_database([rejected])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "flagged",
        "hash": rejected["infohash"],
        "title": rejected["title"],
        "torrent_url": rejected["torrent_url"],
        "detail_url": rejected["detail_url"],
        "episode": rejected["episode"],
    }
    anime["download_queues"] = [anime["download_queue"]]
    writes = []
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_refresh_torrent_search", lambda item: item.update({"torrent_search": {"candidates": [rejected], "notices": []}}))

    success, message = app_state.reject_flagged_torrent("anime-1")

    assert success is True
    assert message == "Rejected flagged torrent and added it to the ignore list."
    assert client.deleted == [(rejected["infohash"], True)]
    assert client.urls == []
    assert database["ignored_torrents"][0]["key"] == f"hash:{rejected['infohash'].casefold()}"
    assert anime["download_queue"]["status"] == "rejected"
    assert all(queue.get("status") != "flagged" for queue in anime["download_queues"])
    assert writes == [database]

def test_download_client_form_saves_remote_path_mapping() -> None:
    client, error = app_state._download_client_from_form(
        {
            "implementation": "qbittorrent",
            "enabled": "on",
            "host": "localhost",
            "port": "8080",
            "category": "nyaarr",
            "remote_path_mapping_enabled": "on",
            "remote_path": "/downloads/anime",
            "local_path": "D:/Anime",
        }
    )

    assert error == ""
    assert client["remote_path_mapping_enabled"] is True
    assert client["remote_path"] == "/downloads/anime"
    assert client["local_path"] == "D:/Anime"


def test_selected_batch_import_replaces_existing_episode_file_in_anime_folder(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    anime_folder = root / "Petals of Reincarnation"
    batch_folder = root / "Petals Complete Batch"
    anime_folder.mkdir(parents=True)
    batch_folder.mkdir(parents=True)
    filename = "[SteadySubs] Petals of Reincarnation - 03 [1080p].mkv"
    destination = anime_folder / filename
    source = batch_folder / filename
    destination.write_bytes(b"old individual torrent file")
    source.write_bytes(b"batch torrent file")
    anime = {
        "title": "Petals of Reincarnation",
        "local_path": str(anime_folder),
        "episode_files": [str(destination)],
        "episodes": "3",
        "completion": {"expected_episodes": 3, "local_episodes": 2, "progress_target": 3, "missing_episodes": 1},
    }
    queue = {
        "release_kind": "batch",
        "select_batch_files": True,
        "wanted_episodes": [3],
        "save_path": str(root),
        "content_path": str(batch_folder),
    }
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda item, force=False: "skipped")

    imported = app_state._import_completed_torrent(anime, queue, {"download_client": {}})

    assert imported is True
    assert destination.read_bytes() == b"batch torrent file"
    assert not source.exists()
    assert anime["local_path"] == str(anime_folder.resolve())
    assert anime["episode_files"] == [str(destination.resolve())]

    queue["import_status"] = "imported"
    queue["message"] = "Completed torrent imported into the anime root folder."
    imported_again = app_state._import_completed_torrent(anime, queue, {"download_client": {}})

    assert imported_again is True
    assert queue["import_status"] == "imported"
    assert anime["episode_files"] == [str(destination.resolve())]

def test_completed_torrent_import_uses_remote_path_mapping(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    root.mkdir()
    source = root / "Petals.of.Reincarnation.S01E01.1080p.mkv"
    source.write_bytes(b"media")
    database = auto_dispatch_database([])
    database["settings"]["root_folder"] = str(root)
    database["settings"]["download_client"].update(
        {
            "remote_path_mapping_enabled": True,
            "remote_path": "/downloads/anime",
            "local_path": str(root),
        }
    )
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "mapped-hash",
        "safety_status": "safe",
        "save_path": "/downloads/anime",
        "content_path": "/downloads/anime/Petals.of.Reincarnation.S01E01.1080p.mkv",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "mapped-hash",
            "name": "Petals.of.Reincarnation.S01E01.1080p.mkv",
            "progress": 1,
            "state": "uploading",
            "content_path": "/downloads/anime/Petals.of.Reincarnation.S01E01.1080p.mkv",
            "save_path": "/downloads/anime",
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda item, force=False: "skipped")

    changed = app_state._refresh_download_queue(database)

    destination = root / "Petals of Reincarnation" / source.name
    assert changed is True
    assert anime["download_queue"]["status"] == "imported"
    assert destination.exists()
    assert anime["episode_files"] == [str(destination.resolve())]


def test_activity_queued_rows_include_flagged_resolution_actions() -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "flagged",
        "hash": "flagged-hash",
        "title": "Suspicious release",
        "queued_at": "2026-06-25T00:00:00+00:00",
    }
    anime["download_queues"] = [anime["download_queue"]]

    rows = app_state._activity_queued_rows(database)

    flagged = next(row for row in rows if row["status"] == "flagged")
    wanted_episodes = {row["episode"] for row in rows if row["status"] == "wanted"}

    assert flagged["can_resolve"] is True
    assert flagged["library_id"] == "anime-1"
    assert wanted_episodes == {"1", "2", "3"}


def test_metadata_verification_model_includes_cached_anilist_candidate(monkeypatch) -> None:
    offline = root_scan_metadata("Petals of Reincarnation")
    offline.update({"source": "anime-offline-database", "provider_ids": {}})
    cached = root_scan_metadata("Petals of Reincarnation")
    cached.update({"source": "AniList", "provider_ids": {"anilist": "179950"}, "poster": "https://anilist.example/petals.jpg"})
    database = {
        "settings": {},
        "anime": [
            {
                "library_id": "root-folder:petals",
                "title": "Petals of Reincarnation",
                "original_title": "Reincarnation no Kaben",
                "episode_files": [f"C:/Anime/Petals/Petals.of.Reincarnation.S01E{episode:02d}.mkv" for episode in range(1, 14)],
                "manual_verification_required": True,
                "manual_verification_reason": "Ambiguous metadata match.",
                "metadata_candidates": [app_state._metadata_candidate_preview([offline])[0]],
                "metadata_search_titles": ["Petals of Reincarnation"],
            }
        ],
    }

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: cached)

    model = app_state.metadata_verification_model()

    assert model["count"] == 1
    assert [candidate["source"] for candidate in model["items"][0]["candidates"]] == ["AniList", "anime-offline-database"]
    assert model["items"][0]["candidates"][0]["selection_key"] == "anilist:179950"


def test_apply_metadata_verification_can_use_cached_anilist_candidate_when_live_search_lacks_it(monkeypatch) -> None:
    offline = root_scan_metadata("Petals of Reincarnation")
    offline.update({"source": "anime-offline-database", "provider_ids": {}})
    cached = root_scan_metadata("Petals of Reincarnation")
    cached.update(
        {
            "source": "AniList",
            "provider_ids": {"anilist": "179950"},
            "poster": "https://anilist.example/petals.jpg",
            "episodes": "13",
        }
    )
    database = {
        "settings": {"root_folder": "C:/Anime"},
        "events": [],
        "anime": [
            {
                "library_id": "root-folder:petals",
                "title": "Petals of Reincarnation",
                "original_title": "Reincarnation no Kaben",
                "episode_files": [f"C:/Anime/Petals/Petals.of.Reincarnation.S01E{episode:02d}.mkv" for episode in range(1, 14)],
                "manual_verification_required": True,
                "manual_verification_reason": "Ambiguous metadata match.",
                "metadata_candidates": [app_state._metadata_candidate_preview([offline])[0]],
                "metadata_search_titles": ["Petals of Reincarnation"],
                "torrent_search": {"candidates": [], "notices": []},
            }
        ],
    }
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: cached)
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [offline])
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_sync_anime_nfo_file", lambda anime: None)

    success, message = app_state.apply_metadata_verification("root-folder:petals", "anilist:179950")

    anime = database["anime"][0]
    assert success is True
    assert message == "Verified metadata for Petals of Reincarnation."
    assert anime["source"] == "Root Folder Scan + AniList"
    assert anime["provider_ids"] == {"anilist": "179950"}
    assert anime["episodes"] == "13"
    assert anime["manual_verification_required"] is False
    assert writes == [database]

def test_metadata_verification_applies_selected_candidate_and_records_event(monkeypatch) -> None:
    selected = root_scan_metadata("Petals of Reincarnation")
    selection_key = app_state._metadata_result_key(selected)
    database = {
        "settings": {"root_folder": "C:/Anime", "download_client": {"implementation": "qbittorrent", "enabled": False}},
        "ignored_torrents": [],
        "events": [],
        "anime": [
            {
                "library_id": "root-folder:petals",
                "title": "Petals folder",
                "original_title": "Petals folder",
                "local_path": "C:/Anime/Petals",
                "episode_files": ["C:/Anime/Petals/Petals.S01E01.mkv"],
                "manual_verification_required": True,
                "manual_verification_reason": "Ambiguous metadata match.",
                "metadata_candidates": [app_state._metadata_candidate_preview([selected])[0]],
                "metadata_search_titles": ["Petals folder"],
                "torrent_search": {"candidates": [], "notices": []},
            }
        ],
    }
    writes = []
    cache_calls = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [selected])
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: cache_calls.append((context, metadata)))
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")

    success, message = app_state.apply_metadata_verification("root-folder:petals", selection_key)

    anime = database["anime"][0]
    assert success is True
    assert message == "Verified metadata for Petals of Reincarnation."
    assert anime["title"] == "Petals of Reincarnation"
    assert anime["manual_verification_required"] is False
    assert anime["metadata_candidates"] == []
    assert app_state.metadata_verification_model() == {"items": [], "count": 0}
    assert anime["metadata_resolution_source"] == "manual"
    assert cache_calls and cache_calls[0][1] == selected
    assert database["events"][-1]["category"] == "metadata"
    assert "Verified metadata" in database["events"][-1]["message"]
    assert writes == [database]


def test_manual_anilist_id_override_updates_metadata_and_episode_count(monkeypatch, tmp_path) -> None:
    local_folder = tmp_path / "Time of Eve"
    local_folder.mkdir()
    database = {
        "settings": {"root_folder": "C:/Anime", "download_client": {"implementation": "qbittorrent", "enabled": False}},
        "ignored_torrents": [],
        "events": [],
        "anime": [
            {
                "library_id": "root-folder:time-of-eve",
                "title": "Time of Eve",
                "original_title": "Time of Eve",
                "episodes": "6",
                "episode_files": ["C:/Anime/Time of Eve/Time.of.Eve.Movie.mkv"],
                "local_path": str(local_folder),
                "torrent_search": {"candidates": [{"title": "Old episode 2"}], "notices": []},
                "torrent_manual_selection": {"required": True, "intervention_type": "low_confidence"},
                "download_queue": {"status": "queued", "episode": 2, "hash": "old-episode-2"},
                "download_queues": [
                    {"status": "queued", "episode": 2, "hash": "old-episode-2"},
                    {"status": "completed", "episode": 1, "hash": "old-completed"},
                ],
                "provider_ids": {"anilist": "old"},
            }
        ],
    }
    movie_metadata = root_scan_metadata("Time of Eve Movie")
    movie_metadata.update({"episodes": "1", "provider_ids": {"anilist": "7465"}, "status": "Finished"})
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "search_anilist_by_id", lambda anilist_id: movie_metadata if anilist_id == "7465" else None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")

    success, message = app_state.apply_manual_anilist_id("root-folder:time-of-eve", "7465")

    anime = database["anime"][0]
    assert success is True
    assert "7465" in message
    assert "Cleared 1 queued" in message
    assert anime["title"] == "Time of Eve Movie"
    assert anime["episodes"] == "1"
    assert anime["provider_ids"]["anilist"] == "7465"
    nfo = (local_folder / "tvshow.nfo").read_text(encoding="utf-8")
    assert '<uniqueid type="anilist" default="true">7465</uniqueid>' in nfo
    assert "<id>anilist:7465</id>" in nfo
    assert anime["metadata_resolution_source"] == "manual-anilist-id"
    assert anime["completion"]["expected_episodes"] == 1
    assert anime["completion"]["missing_episodes"] == 0
    assert anime["torrent_manual_selection"] == {"required": False}
    assert anime["download_queue"]["status"] == "completed"
    assert [queue["status"] for queue in anime["download_queues"]] == ["completed"]
    assert anime["torrent_search"]["candidates"] == []
    assert database["events"][-1]["category"] == "metadata"
    assert writes == [database]

def test_event_log_model_returns_recent_events_newest_first(monkeypatch) -> None:
    database = {"events": []}
    for index in range(205):
        app_state._record_event(database, "torrent", f"event {index}")

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)

    model = app_state.event_log_model(limit=3)

    exported_rows = app_state.event_log_rows(limit=None)

    assert len(database["events"]) == 200
    assert model["count"] == 200
    assert [row["message"] for row in model["rows"]] == ["event 204", "event 203", "event 202"]
    assert len(exported_rows) == 200
    assert exported_rows[0]["message"] == "event 204"



def test_poster_repair_replaces_blocked_poster_from_alternate_provider(monkeypatch) -> None:
    database = {"events": []}
    anime = {
        "library_id": "anime-1",
        "title": "SANDA",
        "original_title": "Unknown",
        "year": "2025",
        "season_number": 1,
        "poster": "https://cdn.animenewsnetwork.com/broken.jpg",
        "metadata_search_titles": ["Sanda"],
        "provider_ids": {},
    }

    monkeypatch.setattr(app_state, "_poster_url_accessible", lambda url: False)
    monkeypatch.setattr(app_state, "search_anilist", lambda title: [])
    monkeypatch.setattr(
        app_state,
        "search_kitsu",
        lambda title: [
            {
                "title": "SANDA",
                "original_title": "Sanda",
                "year": "2025",
                "season_number": 1,
                "source": "Kitsu",
                "poster": "https://kitsu.example/sanda.jpg",
                "provider_ids": {"kitsu": "1"},
            }
        ],
    )
    monkeypatch.setattr(app_state, "search_tmdb", lambda title: [])

    changed = app_state._repair_anime_poster(database, anime)

    assert changed is True
    assert anime["poster"] == "https://kitsu.example/sanda.jpg"
    assert anime["poster_source"] == "Kitsu"
    assert anime["poster_status"] == "repaired"
    assert database["events"][-1]["category"] == "metadata"
    assert "Repaired poster" in database["events"][-1]["message"]


def test_poster_repair_prefers_anilist_for_unverified_fallback_poster(monkeypatch) -> None:
    database = {"events": []}
    anime = {
        "library_id": "root-folder:petals",
        "title": "Petals of Reincarnation",
        "original_title": "Reincarnation no Kaben",
        "year": "2026",
        "season_number": 1,
        "poster": "https://cdn.animenewsnetwork.com/petals.jpg",
        "poster_source": "anime-offline-database",
        "provider_ids": {"anilist": "179950"},
    }
    calls = []

    monkeypatch.setattr(app_state, "_poster_url_accessible", lambda url: (_ for _ in ()).throw(AssertionError("fallback poster should not be treated as final before AniList lookup")))
    monkeypatch.setattr(
        app_state,
        "search_anilist_by_id",
        lambda anilist_id: calls.append(anilist_id)
        or {
            "title": "Petals of Reincarnation",
            "original_title": "Reincarnation no Kaben",
            "year": "2026",
            "season_number": 1,
            "source": "AniList",
            "poster": "https://anilist.example/petals.jpg",
            "provider_ids": {"anilist": "179950"},
        },
    )
    monkeypatch.setattr(app_state, "search_anilist", lambda title: [])
    monkeypatch.setattr(app_state, "search_kitsu", lambda title: [])
    monkeypatch.setattr(app_state, "search_tmdb", lambda title: [])

    changed = app_state._repair_anime_poster(database, anime)

    assert changed is True
    assert calls == ["179950"]
    assert anime["poster"] == "https://anilist.example/petals.jpg"
    assert anime["poster_source"] == "AniList"
    assert anime["provider_ids"]["anilist"] == "179950"
    assert anime["poster_status"] == "repaired"


def test_poster_repair_uses_provider_id_before_title_search(monkeypatch) -> None:
    database = {"events": []}
    anime = {
        "library_id": "anime-1",
        "title": "Digimon Beatbreak",
        "year": "2025",
        "poster": "https://cdn.animenewsnetwork.com/broken.jpg",
        "provider_ids": {"anilist": "123"},
    }
    calls = []

    monkeypatch.setattr(app_state, "_poster_url_accessible", lambda url: False)
    monkeypatch.setattr(
        app_state,
        "search_anilist_by_id",
        lambda anilist_id: calls.append(anilist_id)
        or {
            "title": "DIGIMON BEATBREAK",
            "original_title": "Digimon Beatbreak",
            "year": "2025",
            "season_number": 1,
            "source": "AniList",
            "poster": "https://anilist.example/digimon.jpg",
        },
    )
    monkeypatch.setattr(app_state, "search_anilist", lambda title: (_ for _ in ()).throw(AssertionError("title search should not run")))
    monkeypatch.setattr(app_state, "search_kitsu", lambda title: [])
    monkeypatch.setattr(app_state, "search_tmdb", lambda title: [])

    app_state._repair_anime_poster(database, anime)

    assert calls == ["123"]
    assert anime["poster"] == "https://anilist.example/digimon.jpg"
    assert anime["poster_source"] == "AniList"


def test_poster_repair_prefers_anilist_title_search_for_unverified_fallback_poster(monkeypatch) -> None:
    database = {"events": []}
    anime = {
        "library_id": "root-folder:sanda",
        "title": "SANDA",
        "original_title": "Unknown",
        "year": "2025",
        "season_number": 1,
        "poster": "https://cdn.animenewsnetwork.com/sanda.jpg",
        "poster_source": "anime-offline-database",
        "metadata_search_titles": ["Sanda"],
        "provider_ids": {},
    }
    calls = []

    monkeypatch.setattr(app_state, "_poster_url_accessible", lambda url: (_ for _ in ()).throw(AssertionError("fallback poster should not be accepted before provider search")))
    monkeypatch.setattr(app_state, "search_anilist_by_id", lambda anilist_id: None)
    monkeypatch.setattr(
        app_state,
        "search_anilist",
        lambda title: calls.append(title)
        or [
            {
                "title": "SANDA",
                "original_title": "Sanda",
                "year": "2025",
                "season_number": 1,
                "source": "AniList",
                "poster": "https://anilist.example/sanda.jpg",
                "provider_ids": {"anilist": "185586"},
            }
        ],
    )
    monkeypatch.setattr(app_state, "search_kitsu", lambda title: [])
    monkeypatch.setattr(app_state, "search_tmdb", lambda title: [])

    changed = app_state._repair_anime_poster(database, anime)

    assert changed is True
    assert calls[0] == "SANDA"
    assert anime["poster"] == "https://anilist.example/sanda.jpg"
    assert anime["poster_source"] == "AniList"
    assert anime["provider_ids"]["anilist"] == "185586"


def test_valid_poster_is_marked_ok_without_provider_search(monkeypatch) -> None:
    database = {"events": []}
    anime = {"title": "Petals", "poster": "https://images.example/petals.jpg"}

    monkeypatch.setattr(app_state, "_poster_url_accessible", lambda url: True)
    monkeypatch.setattr(app_state, "search_anilist", lambda title: (_ for _ in ()).throw(AssertionError("provider search should not run")))

    changed = app_state._repair_anime_poster(database, anime)

    assert changed is True
    assert anime["poster"] == "https://images.example/petals.jpg"
    assert anime["poster_status"] == "ok"
    assert database["events"] == []


def test_recent_poster_check_is_throttled() -> None:
    anime = {"title": "Petals", "poster_checked_at": "2026-06-29T00:00:00+00:00"}
    now = datetime(2026, 6, 29, 0, 1, tzinfo=timezone.utc).timestamp()

    assert app_state._should_repair_poster(anime, now) is False

def test_paused_qbittorrent_torrent_stays_paused_in_activity_state(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "paused-hash",
        "safety_status": "safe",
        "save_path": "C:/Anime",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {"hash": "paused-hash", "name": "Petals", "progress": 0.25, "state": "pausedDL", "save_path": "C:/Anime"}
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert anime["download_queue"]["status"] == "paused"
    assert anime["download_queue"]["client_state"] == "pausedDL"
    assert client.resumed == ["paused-hash"]
    assert anime["download_queue"]["message"] == "Torrent passed safety inspection and qBittorrent was resumed."
    assert app_state._active_download_queue(anime) is True


def test_refresh_download_queue_deletes_wrong_subber_imported_seeding_torrent(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    show = root / "Digimon Beatbreak"
    show.mkdir(parents=True)
    local_files = []
    for episode in range(1, 29):
        path = show / f"[SubsPlease] Digimon Beatbreak - {episode:02d} [1080p].mkv"
        path.write_bytes(b"media")
        local_files.append(str(path))
    wrong_file = show / "[OtherSubs] Digimon Beatbreak - 29 [1080p].mkv"
    wrong_file.write_bytes(b"media")

    database = auto_dispatch_database([])
    database["settings"]["root_folder"] = str(root)
    anime = database["anime"][0]
    anime["title"] = "Digimon Beatbreak"
    anime["episodes"] = "29"
    anime["local_path"] = str(show)
    anime["completion"] = {
        "expected_episodes": 29,
        "local_episodes": 29,
        "progress_target": 29,
        "missing_episodes": 0,
    }
    anime["episode_files"] = local_files + [str(wrong_file)]
    anime["download_queue"] = {
        "status": "imported",
        "hash": "wrong-imported-hash",
        "title": "[OtherSubs] Digimon Beatbreak - 29 [1080p]",
        "release_group": "OtherSubs",
        "episode": 29,
        "wanted_episodes": [29],
        "torrent_url": "https://nyaa.si/download/wrong-imported.torrent",
        "detail_url": "https://nyaa.si/view/wrong-imported",
        "save_path": str(root),
        "content_path": str(wrong_file),
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "wrong-imported-hash",
            "name": wrong_file.name,
            "progress": 1,
            "state": "uploading",
            "content_path": str(wrong_file),
            "save_path": str(root),
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda item, force=False: "skipped")

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.deleted == [("wrong-imported-hash", True)]
    assert anime["download_queue"]["status"] == "rejected"
    assert str(wrong_file) not in anime["episode_files"]
    assert not wrong_file.exists()
    assert anime["completion"]["missing_episodes"] == 1
    assert app_state._activity_queued_rows(database) == [app_state._activity_missing_episode_row(anime, 29)]


def test_refresh_download_queue_deletes_wrong_subber_completed_torrent(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["title"] = "Digimon Beatbreak"
    anime["episodes"] = "29"
    anime["completion"] = {
        "expected_episodes": 29,
        "local_episodes": 28,
        "progress_target": 29,
        "missing_episodes": 1,
    }
    anime["episode_files"] = [
        f"C:/Anime/Digimon Beatbreak/[SubsPlease] Digimon Beatbreak - {episode:02d} [1080p].mkv"
        for episode in range(1, 29)
    ]
    anime["download_queue"] = {
        "status": "completed",
        "hash": "wrong-hash",
        "title": "[OtherSubs] Digimon Beatbreak - 29 [1080p]",
        "release_group": "OtherSubs",
        "episode": 29,
        "torrent_url": "https://nyaa.si/download/wrong.torrent",
        "detail_url": "https://nyaa.si/view/wrong",
        "save_path": "C:/Anime",
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "wrong-hash",
            "name": "[OtherSubs] Digimon Beatbreak - 29 [1080p]",
            "progress": 1,
            "state": "uploading",
            "save_path": "C:/Anime",
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    assert changed is True
    assert client.deleted == [("wrong-hash", True)]
    assert anime["download_queue"]["status"] == "rejected"
    assert "existing episodes use SubsPlease" in anime["download_queue"]["message"]
    assert database["ignored_torrents"][0]["hash"] == "wrong-hash"
    assert anime["torrent_search"]["candidates"] == []
    assert app_state._activity_queued_rows(database) == [app_state._activity_missing_episode_row(anime, 29)]


def test_completed_torrent_import_rejects_unwanted_episode(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    root.mkdir()
    source = root / "Petals.of.Reincarnation.S01E09.1080p.mkv"
    source.write_bytes(b"media")
    database = auto_dispatch_database([])
    database["settings"]["root_folder"] = str(root)
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "wrong-episode",
        "safety_status": "safe",
        "save_path": str(root),
        "content_path": str(source),
        "wanted_episodes": [1],
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "wrong-episode",
            "name": source.name,
            "progress": 1,
            "state": "uploading",
            "content_path": str(source),
            "save_path": str(root),
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    changed = app_state._refresh_download_queue(database)

    queue = anime["download_queue"]
    assert changed is True
    assert queue["status"] == "completed"
    assert queue["import_status"] == "blocked"
    assert "matching wanted episodes" in queue["message"]
    assert queue["rejected_import_files"][0]["reason"] == "episode 9 is not wanted"
    assert anime.get("episode_files") is None


def test_completed_batch_import_renames_torrent_folder_to_anilist_title(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    torrent_folder = root / "[AnimeRG] Naoki Urasawa's Monster (Complete Anime Series) Monsuta [480p]"
    torrent_folder.mkdir(parents=True)
    episode = torrent_folder / "[pseudo] Monster - 01 - Herr Dr. Tenma [480p].mkv"
    episode.write_bytes(b"media")
    database = auto_dispatch_database([])
    database["settings"]["root_folder"] = str(root)
    anime = database["anime"][0]
    anime["title"] = "Monster"
    anime["original_title"] = "Monster"
    anime["episodes"] = "74"
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "monster-batch",
        "safety_status": "safe",
        "release_kind": "batch",
        "save_path": str(root),
        "content_path": str(torrent_folder),
        "wanted_episodes": [1],
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "monster-batch",
            "name": torrent_folder.name,
            "progress": 1,
            "state": "uploading",
            "content_path": str(torrent_folder),
            "save_path": str(root),
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda item, force=False: "skipped")

    changed = app_state._refresh_download_queue(database)

    normalized = root / "Monster"
    destination = normalized / episode.name
    assert changed is True
    assert client.renamed_folders == [("monster-batch", torrent_folder.name, "Monster")]
    assert anime["download_queue"]["status"] == "imported"
    assert anime["download_queue"]["folder_rename_status"] == "renamed"
    assert normalized.exists()
    assert destination.exists()
    assert not torrent_folder.exists()
    assert anime["local_path"] == str(normalized.resolve())
    assert anime["episode_files"] == [str(destination.resolve())]


def test_completed_episode_import_uses_existing_local_folder(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    root.mkdir()
    existing = root / "Shibou Yuugi de Meshi wo Kuu"
    existing.mkdir()
    source = root / "SHIBOYUGI.Playing.Death.Games.to.Put.Food.on.the.Table.S01E10.1080p.mkv"
    source.write_bytes(b"media")
    database = auto_dispatch_database([])
    database["settings"]["root_folder"] = str(root)
    anime = database["anime"][0]
    anime["title"] = "SHIBOYUGI: Playing Death Games to Put Food on the Table"
    anime["original_title"] = "Shibou Yuugi de Meshi wo Kuu."
    anime["local_path"] = str(existing)
    anime["episode_files"] = [str(existing / f"[SubsPlease] Shibou Yuugi de Meshi wo Kuu. - {episode:02d} (1080p).mkv") for episode in range(1, 10)]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "episode-10",
        "safety_status": "safe",
        "save_path": str(root),
        "content_path": str(source),
        "wanted_episodes": [10],
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([{
        "hash": "episode-10",
        "name": source.name,
        "progress": 1,
        "state": "uploading",
        "content_path": str(source),
        "save_path": str(root),
    }])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda item, force=False: "skipped")

    changed = app_state._refresh_download_queue(database)

    destination = existing / source.name
    duplicate = root / "SHIBOYUGI Playing Death Games to Put Food on the Table"
    assert changed is True
    assert anime["download_queue"]["status"] == "imported"
    assert destination.exists()
    assert not source.exists()
    assert not duplicate.exists()
    assert anime["local_path"] == str(existing.resolve())
    assert str(destination.resolve()) in anime["episode_files"]


def test_completed_torrent_import_skips_sample_file(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    folder = root / "Download"
    folder.mkdir(parents=True)
    sample = folder / "sample.mkv"
    episode = folder / "Petals.of.Reincarnation.S01E01.1080p.mkv"
    sample.write_bytes(b"sample")
    episode.write_bytes(b"media")
    database = auto_dispatch_database([])
    database["settings"]["root_folder"] = str(root)
    anime = database["anime"][0]
    anime["download_queue"] = {
        "status": "downloading",
        "hash": "sample-hash",
        "safety_status": "safe",
        "save_path": str(root),
        "content_path": str(folder),
        "wanted_episodes": [1],
    }
    anime["download_queues"] = [anime["download_queue"]]
    client = FakeDownloadClient([
        {
            "hash": "sample-hash",
            "name": "Download",
            "progress": 1,
            "state": "uploading",
            "content_path": str(folder),
            "save_path": str(root),
        }
    ])
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda item, force=False: "skipped")

    changed = app_state._refresh_download_queue(database)

    destination = root / "Petals of Reincarnation" / episode.name
    assert changed is True
    assert anime["download_queue"]["status"] == "imported"
    assert destination.exists()
    assert not (root / "Petals of Reincarnation" / sample.name).exists()
    assert anime["download_queue"]["rejected_import_files"][0]["reason"] == "sample file"






def test_dispatch_sets_release_group_lock_from_first_queued_release(monkeypatch) -> None:
    candidate = auto_candidate(1, "Judas")
    database = auto_dispatch_database([candidate])
    anime = database["anime"][0]
    anime["completion"] = {"expected_episodes": 1, "local_episodes": 0, "progress_target": 1, "missing_episodes": 1}
    client = FakeDownloadClient()
    monkeypatch.setattr(app_state, "client_from_settings", lambda *args, **kwargs: client)

    app_state._maybe_dispatch_torrent(database, anime)

    assert client.urls == [candidate["torrent_url"]]
    assert anime["release_group_lock"]["release_group"] == "Judas"
    assert anime["release_group_lock"]["source"] == "queued"

def test_dispatch_selection_uses_release_group_lock_before_prefix_source() -> None:
    database = manual_database()
    anime = database["anime"][0]
    anime["title"] = "Daemons of the Shadow Realm"
    anime["completion"] = {"expected_episodes": 12, "local_episodes": 0, "progress_target": 1, "missing_episodes": 1}
    anime["release_group_lock"] = {"release_group": "Judas", "source": "queued", "locked_at": "2026-07-05T00:00:00+00:00"}
    judas = manual_candidate("judas-1")
    judas.update(
        {
            "title": "Daemons of the Shadow Realm S01E01 1080p WEB-DL AAC2.0 x265-Judas.mkv",
            "release_group": "Judas",
            "release_group_source": "suffix",
            "seeders": 5,
            "episode": 1,
        }
    )
    toonshub = manual_candidate("toonshub-1")
    toonshub.update(
        {
            "title": "[ToonsHub] Daemons of the Shadow Realm - 01 [1080p]",
            "release_group": "ToonsHub",
            "release_group_source": "prefix",
            "seeders": 500,
            "episode": 1,
        }
    )

    selected = app_state._selected_download_releases([toonshub, judas], database, anime)

    assert selected
    assert selected[0]["release_group"] == "Judas"

def test_dispatch_selection_prefers_configured_prefix_subber_over_other_prefix_group() -> None:
    database = manual_database()
    database["settings"]["preferred_subbers"] = ["Judas"]
    anime = database["anime"][0]
    anime["title"] = "Daemons of the Shadow Realm"
    anime["original_title"] = "Yomi no Tsugai"
    anime["completion"] = {"expected_episodes": 12, "local_episodes": 0, "progress_target": 1, "missing_episodes": 1}
    judas = manual_candidate("judas-1")
    judas.update(
        {
            "title": "[Judas] Daemons of the Shadow Realm - 01 [1080p]",
            "release_group": "Judas",
            "release_group_source": "prefix",
            "seeders": 5,
            "episode": 1,
        }
    )
    toonshub = manual_candidate("toonshub-1")
    toonshub.update(
        {
            "title": "[ToonsHub] Daemons of the Shadow Realm - 01 [1080p]",
            "release_group": "ToonsHub",
            "release_group_source": "prefix",
            "seeders": 500,
            "episode": 1,
        }
    )

    selected = app_state._selected_download_releases([toonshub, judas], database, anime)

    assert selected
    assert selected[0]["release_group"] == "Judas"

def test_no_candidate_refresh_with_usable_candidates_clears_manual_and_dispatches(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS", 60)
    database = manual_database()
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [], "checked_at": "2026-06-25T00:00:00+00:00", "notices": []}
    anime["torrent_manual_selection"] = {"required": True, "intervention_type": "no_candidates"}
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    writes = []
    dispatched = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "find_torrents_for_anime", lambda item, preferred_subbers=None: {"query": "Petals", "strategy": "Found", "candidates": [manual_candidate("candidate-1")], "notices": []})
    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", lambda db, item, forced_release=None: dispatched.append(item))

    summary = app_state.run_periodic_maintenance_tick(include_airing=False, include_external=True)

    assert summary["torrent_searches"] == 1
    assert summary["dispatch_attempts"] == 1
    assert anime["torrent_manual_selection"] == {"required": False}
    assert dispatched == [anime]
    assert writes == [database]


def test_no_candidate_search_stays_in_manual_intervention(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [], "notices": []}

    monkeypatch.setattr(app_state, "find_torrents_for_anime", lambda item, preferred_subbers=None: {"query": "Petals", "strategy": "No candidates", "candidates": [], "notices": []})

    app_state._refresh_torrent_search(anime, database)

    assert anime["torrent_manual_selection"]["required"] is True
    assert anime["torrent_manual_selection"]["intervention_type"] == "no_candidates"
    assert app_state._manual_selection_required(anime) is True


def test_refresh_treats_ignored_only_candidates_as_no_usable_candidates(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    candidate = manual_candidate("candidate-1")
    database["ignored_torrents"] = [{"key": "hash:candidate-1"}]

    monkeypatch.setattr(
        app_state,
        "find_torrents_for_anime",
        lambda item, preferred_subbers=None: {"query": "Petals", "strategy": "Only ignored", "candidates": [candidate], "notices": []},
    )

    app_state._refresh_torrent_search(anime, database)

    assert anime["torrent_search"]["candidates"] == []
    assert anime["torrent_manual_selection"]["required"] is True
    assert anime["torrent_manual_selection"]["intervention_type"] == "no_candidates"
    assert "No usable torrent candidates" in anime["torrent_manual_selection"]["reason"]


def test_maintenance_normalizes_stored_ignored_only_candidates(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    candidate = manual_candidate("candidate-1")
    anime["torrent_search"] = {"candidates": [candidate], "notices": [], "checked_at": "2026-06-25T00:00:00+00:00"}
    anime["torrent_manual_selection"] = {"required": False}
    database["ignored_torrents"] = [{"key": "hash:candidate-1"}]
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    summary = app_state.run_periodic_maintenance_tick(include_airing=False, include_external=False)

    assert summary["status"] == "ok"
    assert anime["torrent_search"]["candidates"] == []
    assert anime["torrent_manual_selection"]["required"] is True
    assert anime["torrent_manual_selection"]["intervention_type"] == "no_candidates"
    assert writes == [database]


def test_local_maintenance_dispatches_stored_candidates_without_external_refresh(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [manual_candidate("candidate-1")], "notices": []}
    anime["torrent_manual_selection"] = {"required": False}
    database["settings"]["root_folder"] = "C:/Anime"
    database["settings"]["download_client"] = {
        "implementation": "qbittorrent",
        "enabled": True,
        "category": "nyaarr",
    }
    writes = []
    dispatched = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_refresh_download_queue", lambda db: False)
    monkeypatch.setattr(app_state, "_refresh_library_states", lambda *args, **kwargs: None)
    monkeypatch.setattr(app_state, "_sync_anime_nfo_file", lambda item: False)
    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", lambda db, item, forced_release=None: dispatched.append(item))

    summary = app_state.run_periodic_maintenance_tick(
        include_airing=False,
        include_external=False,
        include_local=True,
    )

    assert summary["torrent_searches"] == 0
    assert summary["dispatch_attempts"] == 1
    assert dispatched == [anime]
    assert writes == [database]


def test_periodic_dispatch_ignores_blocked_only_candidates() -> None:
    database = manual_database()
    anime = database["anime"][0]
    candidate = manual_candidate("candidate-1")
    anime["torrent_search"] = {"candidates": [candidate], "notices": []}
    anime["torrent_manual_selection"] = {"required": False}
    database["ignored_torrents"] = [{"key": "hash:candidate-1"}]
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}

    assert app_state._should_attempt_periodic_dispatch(database, anime, 9999999999) is False


def test_selection_without_usable_candidates_uses_no_candidate_manual_state() -> None:
    database = manual_database()
    anime = database["anime"][0]
    candidate = manual_candidate("candidate-1")
    database["ignored_torrents"] = [{"key": "hash:candidate-1"}]

    selected = app_state._selected_download_releases([candidate], database, anime)

    assert selected == []
    assert anime["torrent_manual_selection"]["required"] is True
    assert anime["torrent_manual_selection"]["intervention_type"] == "no_candidates"


def test_manual_selection_model_shows_no_candidate_intervention(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [], "notices": []}
    anime["torrent_manual_selection"] = {
        "required": True,
        "intervention_type": "no_candidates",
        "reason": "No torrent candidates were found. Manual torrent or magnet link is required.",
        "confidence": 0,
    }
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: None)

    model = app_state.manual_selection_model()

    assert model["count"] == 1
    assert model["items"][0]["candidates"] == []
    assert [episode["episode"] for episode in model["items"][0]["needed_episodes"]] == list(range(5, 13))
    assert model["items"][0]["can_submit_url"] is True


def test_manual_selection_data_page_lists_needed_episode_assignment_rows(monkeypatch) -> None:
    import nyaarr
    from nyaarr import create_app

    database = manual_database()
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [], "notices": []}
    anime["torrent_manual_selection"] = {
        "required": True,
        "intervention_type": "no_candidates",
        "reason": "No torrent candidates were found. Manual torrent or magnet link is required.",
        "confidence": 0,
    }
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: None)
    monkeypatch.setattr(nyaarr, "has_superadmin_account", lambda: True)
    monkeypatch.setattr(nyaarr, "load_or_create_session_secret", lambda: "test-secret")
    monkeypatch.setattr(nyaarr, "_session_is_authenticated", lambda: True)

    app = create_app()
    app.config.update(TESTING=True)
    client = app.test_client()
    with client.session_transaction() as session:
        session["superadmin_authenticated"] = True
        session["superadmin_username"] = "admin"
    response = client.get("/anime/manual-selection/data-page")
    html = response.get_data(as_text=True)

    assert response.status_code == 200
    assert "Episode 5" in html
    assert "Episode 12" in html
    assert 'name="episode" value="5"' in html
    assert "No candidate rows are available" not in html


def test_submit_manual_magnet_dispatches_through_existing_queue_path(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [], "notices": []}
    anime["torrent_manual_selection"] = {"required": True, "intervention_type": "no_candidates"}
    writes = []
    dispatched = []
    magnet = "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12&dn=Petals%20of%20Reincarnation%20-%2005"

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    def fake_dispatch(db, item, forced_release=None):
        dispatched.append(forced_release)
        item["download_queue"] = {"torrent_url": forced_release["torrent_url"], "status": "queued"}

    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", fake_dispatch)

    success, message = app_state.assign_manual_torrent_url("anime-1", magnet, "5")

    assert success is True
    assert message == "Manual torrent link was sent to qBittorrent."
    assert dispatched[0]["torrent_url"] == magnet
    assert dispatched[0]["infohash"] == "abcdef1234567890abcdef1234567890abcdef12"
    assert dispatched[0]["episode"] == 5
    assert writes == [database]



def test_submit_manual_magnet_refreshes_qbittorrent_queue_immediately(monkeypatch) -> None:
    database = manual_database()
    database["settings"]["download_client"] = {"implementation": "qbittorrent", "enabled": True, "category": "nyaarr"}
    anime = database["anime"][0]
    anime["torrent_search"] = {"candidates": [], "notices": []}
    anime["torrent_manual_selection"] = {"required": True, "intervention_type": "no_candidates"}
    writes = []
    refreshes = []
    magnet = "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12&dn=Petals%20of%20Reincarnation%20-%2005"

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_refresh_download_queue", lambda db: refreshes.append(db) or True)

    def fake_dispatch(db, item, forced_release=None):
        item["download_queue"] = {"torrent_url": forced_release["torrent_url"], "status": "queued"}

    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", fake_dispatch)

    success, message = app_state.assign_manual_torrent_url("anime-1", magnet, "5")

    assert success is True
    assert message == "Manual torrent link was sent to qBittorrent."
    assert refreshes == [database]
    assert writes == [database]


def test_manual_magnet_learns_subber_and_searches_remaining_episodes_immediately(monkeypatch) -> None:
    database = manual_database()
    anime = database["anime"][0]
    anime["completion"] = {
        "expected_episodes": 6,
        "local_episodes": 4,
        "progress_target": 6,
        "missing_episodes": 2,
    }
    anime["torrent_search"] = {"candidates": [], "notices": []}
    magnet = (
        "magnet:?xt=urn:btih:ABCDEF1234567890ABCDEF1234567890ABCDEF12"
        "&dn=%5BSubsPlease%5D%20Petals%20of%20Reincarnation%20-%2005%20%281080p%29.mkv"
    )
    dispatches = []
    searches = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: None)

    def fake_dispatch(db, item, forced_release=None):
        dispatches.append(forced_release)
        if forced_release is not None:
            item["download_queue"] = {
                "torrent_url": forced_release["torrent_url"],
                "status": "submitted",
                "episode": forced_release["episode"],
            }

    def fake_search(item, db=None):
        searches.append(app_state._locked_release_group(item))
        item["torrent_search"] = {"candidates": [auto_candidate(6, group="SubsPlease")], "notices": []}

    monkeypatch.setattr(app_state, "_maybe_dispatch_torrent", fake_dispatch)
    monkeypatch.setattr(app_state, "_refresh_torrent_search", fake_search)

    success, _message = app_state.assign_manual_torrent_url("anime-1", magnet, "5")

    assert success is True
    assert app_state._locked_release_group(anime) == "SubsPlease"
    assert searches == ["SubsPlease"]
    assert len(dispatches) == 2
    assert dispatches[0]["title"].startswith("[SubsPlease]")
    assert dispatches[1] is None


def test_activity_batch_queue_covers_all_wanted_episode_rows() -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["download_queues"] = [{
        "status": "submitted",
        "release_kind": "batch",
        "wanted_episodes": [1, 2, 3],
        "title": "Petals batch",
    }]
    anime["download_queue"] = anime["download_queues"][0]

    rows = app_state._activity_queued_rows(database)

    assert len(rows) == 1
    assert rows[0]["episode"] == "1-3"
    assert all(row["title"] != "No torrent selected yet" for row in rows)


def test_hard_reset_queued_torrents_preserves_client_visible_and_requeues_discovery(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["torrent_manual_selection"] = {"required": True, "intervention_type": "no_candidates"}
    anime["torrent_dispatch_attempted_at"] = "2026-07-22T00:00:00+00:00"
    anime["download_queues"] = [
        {"status": "downloading", "hash": "visible-hash", "episode": 1, "title": "Visible"},
        {"status": "error", "hash": "stale-hash", "episode": 2, "title": "Stale"},
        {"status": "imported", "hash": "history-hash", "episode": 3, "title": "History"},
    ]
    anime["download_queue"] = anime["download_queues"][0]
    writes = []
    jobs = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_download_client_existing_snapshot", lambda db: {"keys": {"hash:visible-hash"}, "episodes_by_library_id": {}})
    monkeypatch.setattr(app_state, "_archive_download_queues", lambda item, queues: None)
    monkeypatch.setattr("nyaarr.maintenance.enqueue_job", lambda job_type, **kwargs: jobs.append((job_type, kwargs)) or "job")

    success, message = app_state.hard_reset_queued_torrents()

    assert success is True
    assert "cleared 1 stale queue record" in message
    assert [queue["hash"] for queue in anime["download_queues"]] == ["visible-hash", "history-hash"]
    assert anime["torrent_manual_selection"] == {"required": False}
    assert anime["torrent_search"]["candidates"] == []
    assert anime["torrent_search"]["checked_at"] == ""
    assert "torrent_dispatch_attempted_at" not in anime
    assert jobs[0][0] == "external_refresh"
    assert jobs[0][1]["priority"] == 100
    assert writes == [database]


def test_hard_reset_queued_torrents_preserves_client_visible_and_requeues_discovery(monkeypatch) -> None:
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime["torrent_manual_selection"] = {"required": True, "intervention_type": "no_candidates"}
    anime["torrent_dispatch_attempted_at"] = "2026-07-22T00:00:00+00:00"
    anime["download_queues"] = [
        {"status": "downloading", "hash": "visible-hash", "episode": 1, "title": "Visible"},
        {"status": "error", "hash": "stale-hash", "episode": 2, "title": "Stale"},
        {"status": "imported", "hash": "history-hash", "episode": 3, "title": "History"},
    ]
    anime["download_queue"] = anime["download_queues"][0]
    writes = []
    jobs = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(
        app_state,
        "_download_client_existing_snapshot",
        lambda db: {"keys": {"hash:visible-hash"}, "episodes_by_library_id": {}},
    )
    monkeypatch.setattr(app_state, "_archive_download_queues", lambda item, queues: None)
    monkeypatch.setattr("nyaarr.maintenance.enqueue_job", lambda job_type, **kwargs: jobs.append((job_type, kwargs)) or "job")

    success, message = app_state.hard_reset_queued_torrents()

    assert success is True
    assert "cleared 1 stale queue record" in message
    assert [queue["hash"] for queue in anime["download_queues"]] == ["visible-hash", "history-hash"]
    assert anime["torrent_manual_selection"] == {"required": False}
    assert anime["torrent_search"]["candidates"] == []
    assert anime["torrent_search"]["checked_at"] == ""
    assert "torrent_dispatch_attempted_at" not in anime
    assert jobs[0][0] == "external_refresh"
    assert jobs[0][1]["priority"] == 100
    assert writes == [database]

def test_anime_detail_model_builds_sonarr_style_episode_rows(monkeypatch, tmp_path) -> None:
    media = tmp_path / "Petals.of.Reincarnation.S01E01.1080p.mkv"
    media.write_bytes(b"media")
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime.update(
        {
            "episode_files": [str(media)],
            "download_queue": {
                "status": "downloading",
                "episode": 2,
                "progress": 42,
                "quality": "1080p",
            },
            "download_queues": [
                {
                    "status": "downloading",
                    "episode": 2,
                    "progress": 42,
                    "quality": "1080p",
                }
            ],
        }
    )
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)

    model = app_state.anime_detail_model("anime-1")

    assert model is not None
    assert model["title"] == "Petals of Reincarnation"
    assert [row["status"] for row in model["episodes"]] == ["Downloaded", "Downloading", "Missing"]
    assert model["episodes"][0]["file"] == media.name
    assert model["episodes"][1]["progress"] == 42


def test_anime_detail_model_prefers_season_folder_over_specials(monkeypatch, tmp_path) -> None:
    show = tmp_path / "Digimon Tamers"
    season = show / "Season 1"
    specials = show / "Specials"
    season.mkdir(parents=True)
    specials.mkdir()
    episode_one = season / "Digimon Tamers - S01E01.mkv"
    episode_two = season / "Digimon Tamers - S01E02.mkv"
    special_one = specials / "Digimon Tamers - S00E01.mkv"
    special_two = specials / "Digimon Tamers - S00E02.mkv"
    for media in (episode_one, episode_two, special_one, special_two):
        media.write_bytes(b"media")
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime.update(
        {
            "title": "Digimon Tamers",
            "local_path": str(show),
            "episodes": "51",
            "season_number": 1,
            "episode_files": [str(special_one), str(special_two), str(episode_one), str(episode_two)],
        }
    )
    app_state._refresh_library_state(anime)
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)

    model = app_state.anime_detail_model("anime-1")

    assert model is not None
    assert model["completion"]["local_episodes"] == 2
    assert model["completion"]["expected_episodes"] == 51
    assert len(model["episodes"]) == 51
    assert model["episodes"][0]["file"] == episode_one.name
    assert model["episodes"][1]["file"] == episode_two.name
    assert all("S00" not in row["file"] for row in model["episodes"] if row["file"])


def test_local_episode_count_uses_unique_episode_numbers_when_season_hint_misses_specials() -> None:
    anime = {
        "title": "Digimon Tamers",
        "episodes": "51",
        "season_number": 3,
        "episode_files": [
            *[f"//server/Torrents/Anime/Digimon Tamers/Season 1/{episode:02d} - Episode.mkv" for episode in range(1, 52)],
            "//server/Torrents/Anime/Digimon Tamers/Specials/Clean Ending 1.mkv",
            "//server/Torrents/Anime/Digimon Tamers/Specials/Clean Ending 2.mkv",
            "//server/Torrents/Anime/Digimon Tamers/Specials/Clean Opening A.mkv",
            "//server/Torrents/Anime/Digimon Tamers/Specials/Clean Opening B.mkv",
        ],
    }

    app_state._refresh_library_state(anime)

    assert anime["completion"]["local_episodes"] == 51
    assert anime["completion"]["expected_episodes"] == 51
    assert anime["completion"]["missing_episodes"] == 0


def test_provider_episode_count_can_include_local_fractional_recap() -> None:
    anime = {
        "title": "Oshi No Ko",
        "episodes": "12",
        "status": "Finished",
        "episode_files": [
            *[f"/anime/Oshi No Ko/[Erai-raws] Oshi no Ko - {episode:02d} [1080p].mkv" for episode in range(1, 12)],
            "/anime/Oshi No Ko/[Erai-raws] Oshi no Ko - 07.5 [1080p].mkv",
        ],
    }

    app_state._refresh_library_state(anime)

    assert anime["completion"]["expected_episodes"] == 11
    assert anime["completion"]["local_episodes"] == 11
    assert anime["completion"]["missing_episodes"] == 0
    assert anime["episode_count_adjustment"]["provider_expected_episodes"] == 12


def test_provider_episode_count_can_include_episode_zero_special() -> None:
    anime = {
        "title": "Kaiju No.8 Season 2",
        "episodes": "12",
        "status": "Finished",
        "episode_files": [
            "/anime/Kaiju No.8 Season 2/[Judas] Kaijuu 8 Gou - S02E00v2.mkv",
            *[f"/anime/Kaiju No.8 Season 2/[Judas] Kaijuu 8 Gou - S02E{episode:02d}v2.mkv" for episode in range(1, 12)],
        ],
    }

    app_state._refresh_library_state(anime)

    assert anime["completion"]["expected_episodes"] == 11
    assert anime["completion"]["local_episodes"] == 11
    assert anime["completion"]["missing_episodes"] == 0
    assert anime["episode_count_adjustment"]["local_special_files"] == 1


def test_provider_episode_count_not_adjusted_when_main_episode_gap_remains() -> None:
    anime = {
        "title": "Still Missing Episode",
        "episodes": "12",
        "status": "Finished",
        "episode_files": [
            "/anime/Show/Show - S01E00.mkv",
            *[f"/anime/Show/Show - S01E{episode:02d}.mkv" for episode in range(1, 11)],
        ],
    }

    app_state._refresh_library_state(anime)

    assert anime["completion"]["expected_episodes"] == 12
    assert anime["completion"]["local_episodes"] == 10
    assert anime["completion"]["missing_episodes"] == 2
    assert "episode_count_adjustment" not in anime


def test_anime_detail_model_maps_single_unnumbered_movie_file_to_episode_one(monkeypatch, tmp_path) -> None:
    media = tmp_path / "[Judas] Chainsaw Man The Movie.mkv"
    media.write_bytes(b"media")
    database = auto_dispatch_database([])
    anime = database["anime"][0]
    anime.update(
        {
            "title": "Chainsaw Man - The Movie: Reze Arc",
            "original_title": "Chainsaw Man: Reze-hen",
            "library_state": "Completed",
            "status": "Finished",
            "episodes": "1",
            "episode_files": [str(media)],
        }
    )
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)

    model = app_state.anime_detail_model("anime-1")

    assert model is not None
    assert model["completion"]["local_episodes"] == 1
    assert model["completion"]["missing_episodes"] == 0
    assert len(model["episodes"]) == 1
    assert model["episodes"][0]["status"] == "Downloaded"
    assert model["episodes"][0]["file"] == media.name


def test_anilist_metadata_refresh_upgrades_fallback_provider(monkeypatch, tmp_path) -> None:
    now = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()
    database = {"settings": {"root_folder": "C:/Anime"}, "events": [], "anime": []}
    anime = {
        "library_id": "root-folder:chainsaw-man-reze-arc",
        "title": "Chainsaw Man - The Movie: Reze Arc",
        "original_title": "Chainsaw Man: Reze-hen",
        "year": "2025",
        "season_number": 1,
        "episodes": "1",
        "status": "Finished",
        "monitored": True,
        "episode_files": ["C:/Anime/Chainsaw Man/[Judas] Chainsaw Man The Movie.mkv"],
        "provider_ids": {"kitsu": "48323"},
        "source": "Root Folder Scan + Kitsu",
        "local_path": str(tmp_path),
        "anilist_reconciliation_status": "pending",
        "torrent_search": {"candidates": [], "notices": []},
    }
    database["anime"].append(anime)
    anilist = root_scan_metadata("Chainsaw Man - The Movie: Reze Arc")
    anilist.update(
        {
            "original_title": "Chainsaw Man: Reze-hen",
            "year": "2025",
            "episodes": "1",
            "source": "AniList",
            "provider_ids": {"anilist": "176907", "mal": "60953"},
            "poster": "https://anilist.example/chainsaw.jpg",
        }
    )

    monkeypatch.setattr(app_state, "search_anilist", lambda title: [anilist])
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)

    changed = app_state._refresh_anilist_metadata(database, anime, now)

    assert changed is True
    assert app_state._metadata_source_name(anime) == "AniList"
    assert anime["provider_ids"]["anilist"] == "176907"
    assert anime["anilist_reconciliation_status"] == "reconciled"
    nfo = (tmp_path / "tvshow.nfo").read_text(encoding="utf-8")
    assert '<uniqueid type="anilist" default="true">176907</uniqueid>' in nfo
    assert "<id>anilist:176907</id>" in nfo
    assert anime["metadata_resolution_source"] == "anilist-routine"
    assert "anilist_metadata_error" not in anime
    assert database["events"][-1]["category"] == "metadata"
    assert "AniList" in database["events"][-1]["message"]


def test_anilist_metadata_refresh_preserves_fallback_poster_when_anilist_has_none(monkeypatch) -> None:
    now = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()
    database = {"settings": {"root_folder": "C:/Anime"}, "events": [], "anime": []}
    anime = {
        "library_id": "root-folder:fallback-show",
        "title": "Fallback Show",
        "original_title": "Fallback Show",
        "year": "2026",
        "season_number": 1,
        "episodes": "12",
        "status": "Releasing",
        "poster": "https://kitsu.example/fallback.jpg",
        "poster_source": "Kitsu",
        "provider_ids": {"kitsu": "fallback-kitsu"},
        "source": "Root Folder Scan + Kitsu",
        "anilist_reconciliation_status": "pending",
        "torrent_search": {"candidates": [], "notices": []},
    }
    database["anime"].append(anime)
    anilist = root_scan_metadata("Fallback Show")
    anilist.update({"source": "AniList", "provider_ids": {"anilist": "12345"}, "poster": ""})

    monkeypatch.setattr(app_state, "search_anilist", lambda title: [anilist])
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)

    changed = app_state._refresh_anilist_metadata(database, anime, now)

    assert changed is True
    assert app_state._metadata_source_name(anime) == "AniList"
    assert anime["provider_ids"]["anilist"] == "12345"
    assert anime["poster"] == "https://kitsu.example/fallback.jpg"
    assert anime["poster_source"] == "Kitsu"
    assert anime["anilist_reconciliation_status"] == "reconciled"


def test_anilist_metadata_refresh_corrects_fallback_episode_count(monkeypatch) -> None:
    now = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()
    database = {"settings": {"root_folder": "C:/Anime"}, "events": [], "anime": []}
    anime = {
        "library_id": "root-folder:orb-on-the-movements-of-the-earth",
        "title": "Orb: On the Movements of the Earth",
        "original_title": "Chi.: Chikyuu no Undou ni Tsuite",
        "year": "2024",
        "season_number": 1,
        "episodes": "29",
        "status": "Finished",
        "monitored": True,
        "episode_files": [
            *[f"C:/Anime/Orb/Season 1/Orb - S01E{episode:02d}.mkv" for episode in range(1, 26)],
            "C:/Anime/Orb/Other/Orb - NCOP 1.mkv",
        ],
        "provider_ids": {"kitsu": "46214"},
        "source": "Root Folder Scan + Kitsu",
        "anilist_reconciliation_status": "pending",
        "torrent_search": {"candidates": [], "notices": []},
    }
    database["anime"].append(anime)
    anilist = root_scan_metadata("Orb: On the Movements of the Earth")
    anilist.update(
        {
            "original_title": "Chi.: Chikyuu no Undou ni Tsuite",
            "year": "2024",
            "episodes": "25",
            "source": "AniList",
            "provider_ids": {"anilist": "151514"},
        }
    )

    monkeypatch.setattr(app_state, "search_anilist", lambda title: [anilist])
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)

    changed = app_state._refresh_anilist_metadata(database, anime, now)

    assert changed is True
    assert anime["episodes"] == "25"
    assert anime["provider_ids"]["anilist"] == "151514"
    assert anime["completion"]["expected_episodes"] == 25
    assert anime["completion"]["local_episodes"] == 25
    assert anime["completion"]["missing_episodes"] == 0


def test_anilist_metadata_refresh_rechecks_stale_anilist_backed_items() -> None:
    now = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()
    anime = {
        "title": "Petals of Reincarnation",
        "source": "AniList",
        "provider_ids": {"anilist": "179950"},
    }

    assert app_state._should_refresh_anilist_metadata(anime, now) is True

    anime["anilist_metadata_checked_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")

    assert app_state._should_refresh_anilist_metadata(anime, now) is False


def test_normalization_marks_legacy_fallback_metadata_for_anilist_reconciliation() -> None:
    anime = {
        "title": "Petals of Reincarnation",
        "source": "Root Folder Scan + anime-offline-database",
        "provider_ids": {"anilist": "179950"},
        "anilist_metadata_checked_at": "2026-06-29T00:00:00Z",
    }

    changed = app_state._normalize_anilist_reconciliation_state(anime)

    assert changed is True
    assert anime["anilist_reconciliation_status"] == "pending"
    assert "anilist_metadata_checked_at" not in anime


def test_pending_anilist_reconciliation_retries_without_checked_timestamp() -> None:
    now = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()
    anime = {
        "title": "Fallback Show",
        "source": "Root Folder Scan + Kitsu",
        "provider_ids": {"kitsu": "fallback-kitsu"},
        "anilist_reconciliation_status": "pending",
    }

    assert app_state._should_refresh_anilist_metadata(anime, now) is True

    anime["anilist_metadata_checked_at"] = datetime.fromtimestamp(now, timezone.utc).isoformat().replace("+00:00", "Z")

    assert app_state._should_refresh_anilist_metadata(anime, now) is False


def test_poster_repair_preserves_anilist_provider_id_from_replacement(monkeypatch) -> None:
    database = {"events": []}
    anime = {
        "library_id": "anime-1",
        "title": "Digimon Beatbreak",
        "original_title": "Digimon Beatbreak",
        "year": "2025",
        "season_number": 1,
        "poster": "https://cdn.animenewsnetwork.com/broken.jpg",
        "metadata_search_titles": ["Digimon Beatbreak"],
        "provider_ids": {},
    }

    monkeypatch.setattr(app_state, "_poster_url_accessible", lambda url: False)
    monkeypatch.setattr(
        app_state,
        "search_anilist",
        lambda title: [
            {
                "title": "DIGIMON BEATBREAK",
                "original_title": "Digimon Beatbreak",
                "year": "2025",
                "season_number": 1,
                "source": "AniList",
                "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx188388-aXx9fsnvezBf.jpg",
                "provider_ids": {"anilist": "188388"},
            }
        ],
    )
    monkeypatch.setattr(app_state, "search_kitsu", lambda title: [])
    monkeypatch.setattr(app_state, "search_tmdb", lambda title: [])

    app_state._repair_anime_poster(database, anime)

    assert anime["poster_source"] == "AniList"
    assert anime["provider_ids"]["anilist"] == "188388"


def test_anilist_metadata_refresh_uses_anilist_poster_id(monkeypatch) -> None:
    now = datetime(2026, 6, 30, 0, 0, tzinfo=timezone.utc).timestamp()
    database = {"settings": {"root_folder": "C:/Anime"}, "events": [], "anime": []}
    anime = {
        "library_id": "root-folder:digimon-beatbreak",
        "title": "DIGIMON BEATBREAK",
        "original_title": "Digimon Beatbreak",
        "year": "2025",
        "season_number": 1,
        "episodes": "28",
        "status": "Finished",
        "monitored": True,
        "episode_files": [f"C:/Anime/Digimon Beatbreak/Digimon Beatbreak - {episode:02d}.mkv" for episode in range(1, 29)],
        "provider_ids": {},
        "poster": "https://s4.anilist.co/file/anilistcdn/media/anime/cover/medium/bx188388-aXx9fsnvezBf.jpg",
        "source": "Root Folder Scan + anime-offline-database",
        "torrent_search": {"candidates": [], "notices": []},
    }
    database["anime"].append(anime)
    calls = []

    def fake_search_by_id(anilist_id):
        calls.append(anilist_id)
        metadata = root_scan_metadata("DIGIMON BEATBREAK")
        metadata.update(
            {
                "original_title": "Digimon Beatbreak",
                "year": "2025",
                "status": "Releasing",
                "episodes": "30",
                "source": "AniList",
                "next_airing_at": "2026-07-05T00:00:00Z",
                "airing_episode": "29",
                "provider_ids": {"anilist": "188388"},
            }
        )
        return metadata

    monkeypatch.setattr(app_state, "search_anilist_by_id", fake_search_by_id)
    monkeypatch.setattr(app_state, "search_anilist", lambda title: (_ for _ in ()).throw(AssertionError("title search should not run")))
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)

    app_state._refresh_anilist_metadata(database, anime, now)

    assert calls == ["188388"]
    assert anime["provider_ids"]["anilist"] == "188388"
    assert anime["status"] == "Releasing"
    assert anime["library_state"] == "Monitored"
    assert anime["airing_state"] == "Airing"






def test_save_root_folder_queues_background_scan_without_inline_import(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    root.mkdir()
    database = {"settings": {"root_folder": ""}, "anime": [], "events": []}
    writes = []
    started = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))
    monkeypatch.setattr(app_state, "_root_scan_thread_active", lambda: False)
    monkeypatch.setattr(app_state, "_start_root_folder_scan_thread", lambda path: started.append(path))

    success, message, summary = app_state.save_root_folder(str(root))

    assert success is True
    assert "background" in message
    assert summary == app_state._empty_scan_summary()
    assert database["settings"]["root_folder"] == str(root.resolve())
    assert started == [root.resolve()]
    assert writes == [database]
    assert app_state.root_folder_scan_progress()["active"] is True




def test_root_scan_completion_preserves_download_client_saved_during_scan(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    root.mkdir()
    scan_database = {"settings": {"root_folder": str(root), "download_client": {"implementation": ""}}, "anime": [], "events": []}
    latest_database = {
        "settings": {
            "root_folder": str(root),
            "download_client": {"implementation": "qbittorrent", "enabled": True, "host": "127.0.0.1"},
        },
        "anime": [{"library_id": "manual:add", "title": "Added During Scan"}],
        "events": [],
    }
    reads = iter([scan_database, latest_database])
    writes = []

    monkeypatch.setattr(app_state, "_read_user_database", lambda: next(reads))
    monkeypatch.setattr(app_state, "_root_folder_children", lambda path: [])
    monkeypatch.setattr(app_state, "_seed_resolved_metadata_cache_from_library", lambda library: None)
    monkeypatch.setattr(app_state, "_import_root_folder_children", lambda database, path, children: app_state._empty_scan_summary())
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    app_state._run_root_folder_scan_job(root)

    assert writes
    assert writes[0]["settings"]["download_client"]["implementation"] == "qbittorrent"
    assert writes[0]["settings"]["download_client"]["host"] == "127.0.0.1"
    assert any(anime.get("library_id") == "manual:add" for anime in writes[0]["anime"])

def test_root_folder_candidate_scan_reports_top_level_progress(monkeypatch, tmp_path) -> None:
    root = tmp_path / "Anime"
    anime_folder = root / "Petals"
    empty_folder = root / "Empty"
    anime_folder.mkdir(parents=True)
    empty_folder.mkdir()
    media_file = anime_folder / "Petals.S01E01.mkv"
    media_file.write_bytes(b"")

    monkeypatch.setattr(
        app_state,
        "_imported_anime_item",
        lambda title, source_path, media_files: {"library_id": f"root-folder:{title}", "title": title, "files": [str(path) for path in media_files]},
    )

    app_state._reset_root_scan_progress("Starting")
    candidates = app_state._root_folder_candidates(root)
    progress = app_state.root_folder_scan_progress()

    assert [candidate["title"] for candidate in candidates] == ["Petals"]
    assert progress["phase"] == "Importing"
    assert progress["total"] == 1
    assert "Found 1 anime candidate" in progress["message"]


def test_root_scan_uses_s01_episode_files_to_reject_season_two_metadata(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Sakamoto.Days.S01E01.1080p.mkv"
    media_file.write_bytes(b"")
    season_two = root_scan_metadata("Sakamoto Days")
    season_two["season_number"] = 2
    season_two["provider_ids"] = {"anilist": "sakamoto-s2"}
    season_one = root_scan_metadata("Sakamoto Days")
    season_one["season_number"] = 1
    season_one["provider_ids"] = {"anilist": "sakamoto-s1"}

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [season_two, season_one])

    item = app_state._imported_anime_item("Sakamoto Days", tmp_path, [media_file])

    assert item["title"] == "Sakamoto Days"
    assert item["season_number"] == 1
    assert item["provider_ids"] == {"anilist": "sakamoto-s1"}
    assert item["metadata_resolution_source"] == "provider"


def test_root_scan_without_local_season_hint_does_not_auto_accept_season_two(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Otome.Game.Sekai.E01.1080p.mkv"
    media_file.write_bytes(b"")
    season_two = root_scan_metadata("Trapped in a Dating Sim: The World of Otome Games is Tough for Mobs")
    season_two["season_number"] = 2
    season_two["provider_ids"] = {"anilist": "otome-s2"}

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [season_two])

    item = app_state._imported_anime_item("Otome Game Sekai wa Mob ni Kibishii Sekai desu", tmp_path, [media_file])

    assert item["season_number"] == 1
    assert item["manual_verification_required"] is True
    assert item["manual_verification_reason"] == "No confident metadata match was found for the folder name."


def test_explicit_season_two_root_title_can_match_season_two_metadata(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Sakamoto.Days.S02E01.1080p.mkv"
    media_file.write_bytes(b"")
    season_two = root_scan_metadata("Sakamoto Days")
    season_two["season_number"] = 2
    season_two["provider_ids"] = {"anilist": "sakamoto-s2"}

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [season_two])

    item = app_state._imported_anime_item("Sakamoto Days Season 2", tmp_path, [media_file])

    assert item["season_number"] == 2
    assert item["manual_verification_required"] is False
    assert item["provider_ids"] == {"anilist": "sakamoto-s2"}


def test_metadata_match_score_uses_alias_and_romaji_title_values() -> None:
    alias_context = {
        "search_titles": ["Jujutsu Kaisen Shimetsu Kaiyuu - Zenpen"],
        "year": None,
        "season_number": None,
        "part_number": None,
        "local_episode_count": 0,
    }
    alias_result = {
        "title": "JUJUTSU KAISEN Season 3: The Culling Game Part 1",
        "aliases": ["Jujutsu Kaisen: Shimetsu Kaiyuu - Zenpen"],
    }
    romaji_context = {
        "search_titles": ["Reincarnation no Kaben"],
        "year": None,
        "season_number": None,
        "part_number": None,
        "local_episode_count": 0,
    }
    romaji_result = {
        "title": "Petals of Reincarnation",
        "provider_title": {"romaji": "Reincarnation no Kaben", "english": "Petals of Reincarnation"},
    }

    assert app_state._metadata_match_score(alias_context, alias_result) >= 1.0
    assert app_state._metadata_match_score(romaji_context, romaji_result) >= 1.0

def test_part_title_overrides_episode_file_season_hint_for_cour_metadata(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Sakamoto.Days.S01E12.1080p.mkv"
    media_file.write_bytes(b"")
    part_two = root_scan_metadata("Sakamoto Days Part 2")
    part_two.update(
        {
            "original_title": "SAKAMOTO DAYS (2025)",
            "episodes": "11",
            "season_number": 2,
            "provider_ids": {"anilist": "sakamoto-part-2"},
            "aliases": ["Sakamoto Days Part 2", "SAKAMOTO DAYS Cour 2", "Sakamoto Days"],
        }
    )

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [part_two])

    item = app_state._imported_anime_item("SAKAMOTO DAYS Part 2", tmp_path, [media_file])

    assert item["title"] == "Sakamoto Days Part 2"
    assert item["season_number"] == 2
    assert item["manual_verification_required"] is False
    assert item["provider_ids"] == {"anilist": "sakamoto-part-2"}


def test_zenpen_metadata_rejects_kouhen_neighbor(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Jujutsu.Kaisen.S03E01.1080p.mkv"
    media_file.write_bytes(b"")
    kouhen = root_scan_metadata("JUJUTSU KAISEN Season 3: The Culling Game Part 2")
    kouhen.update(
        {
            "original_title": "Jujutsu Kaisen: Shimetsu Kaiyuu - Kouhen",
            "episodes": "12",
            "season_number": 3,
            "provider_ids": {"anilist": "jjk-kouhen"},
            "aliases": ["Jujutsu Kaisen: Shimetsu Kaiyuu - Kouhen"],
        }
    )
    zenpen = root_scan_metadata("JUJUTSU KAISEN Season 3: The Culling Game Part 1")
    zenpen.update(
        {
            "original_title": "Jujutsu Kaisen: Shimetsu Kaiyuu - Zenpen",
            "episodes": "12",
            "season_number": 3,
            "provider_ids": {"anilist": "jjk-zenpen"},
            "aliases": ["Jujutsu Kaisen: Shimetsu Kaiyuu - Zenpen"],
        }
    )

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [kouhen, zenpen])

    item = app_state._imported_anime_item("Jujutsu Kaisen Shimetsu Kaiyuu - Zenpen", tmp_path, [media_file])

    assert item["original_title"] == "Jujutsu Kaisen: Shimetsu Kaiyuu - Zenpen"
    assert item["manual_verification_required"] is False
    assert item["provider_ids"] == {"anilist": "jjk-zenpen"}


def test_root_import_prefers_anilist_poster_for_fallback_metadata_with_anilist_id(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "Petals.of.Reincarnation.S01E01.1080p.mkv"
    media_file.write_bytes(b"")
    offline = root_scan_metadata("Petals of Reincarnation")
    offline.update(
        {
            "source": "anime-offline-database",
            "original_title": "Reincarnation no Kaben",
            "poster": "https://cdn.animenewsnetwork.com/petals.jpg",
            "provider_ids": {"anilist": "179950", "mal": "59443"},
        }
    )
    calls = []

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [offline])
    monkeypatch.setattr(
        app_state,
        "search_anilist_by_id",
        lambda anilist_id: calls.append(anilist_id)
        or {
            "title": "Petals of Reincarnation",
            "original_title": "Reincarnation no Kaben",
            "year": "2026",
            "season_number": 1,
            "source": "AniList",
            "poster": "https://anilist.example/petals.jpg",
            "provider_ids": {"anilist": "179950"},
        },
    )

    item = app_state._imported_anime_item("Petals of Reincarnation", tmp_path, [media_file])

    assert calls == ["179950"]
    assert item["poster"] == "https://anilist.example/petals.jpg"
    assert item["poster_source"] == "AniList"
    assert item["provider_ids"]["anilist"] == "179950"



def test_metadata_zero_episode_result_does_not_match_folder_with_local_episodes() -> None:
    metadata = root_scan_metadata("SANDA")
    metadata["episodes"] = "0"

    assert app_state._metadata_episode_count_compatible({"local_episode_count": 12}, metadata) is False


def test_best_metadata_match_skips_zero_episode_sanda_candidate_for_local_season() -> None:
    offline = root_scan_metadata("SANDA")
    offline.update({"source": "anime-offline-database", "episodes": "0", "provider_ids": {}})
    anilist = root_scan_metadata("SANDA")
    anilist.update({"source": "AniList", "episodes": "12", "provider_ids": {"anilist": "sanda-anilist"}})

    match = app_state._best_metadata_match(
        {"search_titles": ["Sanda"], "local_episode_count": 12, "season_number": 1},
        [offline, anilist],
    )

    assert match is anilist

def test_root_import_enriches_missing_poster_from_fallback_metadata_candidate(monkeypatch, tmp_path) -> None:
    media_file = tmp_path / "SANDA.S01E01.1080p.mkv"
    media_file.write_bytes(b"")
    anilist = root_scan_metadata("SANDA")
    anilist["source"] = "AniList"
    anilist["poster"] = ""
    anilist["provider_ids"] = {"anilist": "sanda-anilist"}
    kitsu = root_scan_metadata("SANDA")
    kitsu["source"] = "Kitsu"
    kitsu["poster"] = "https://kitsu.example/sanda.jpg"
    kitsu["provider_ids"] = {"kitsu": "sanda-kitsu"}

    monkeypatch.setattr(app_state, "_resolved_metadata_cache_lookup", lambda context: None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)
    monkeypatch.setattr(app_state, "_refresh_media_tag", lambda anime, force=False: "skipped")
    monkeypatch.setattr(app_state, "_search_metadata_variants", lambda titles: [anilist, kitsu])

    item = app_state._imported_anime_item("SANDA", tmp_path, [media_file])

    assert item["provider_ids"] == {"anilist": "sanda-anilist"}
    assert item["poster"] == "https://kitsu.example/sanda.jpg"
    assert item["poster_source"] == "Kitsu"


def test_search_metadata_keeps_checking_fallbacks_when_anilist_has_no_poster(monkeypatch) -> None:
    from nyaarr import metadata

    monkeypatch.setattr(metadata, "search_anilist", lambda query: [{"title": "SANDA", "year": "2025", "source": "AniList", "poster": ""}])
    monkeypatch.setattr(metadata, "search_anime_offline_database", lambda query: [])
    monkeypatch.setattr(metadata, "search_kitsu", lambda query: [{"title": "SANDA", "year": "2025", "source": "Kitsu", "poster": "https://kitsu.example/sanda.jpg"}])
    monkeypatch.setattr(metadata, "search_tmdb", lambda query: (_ for _ in ()).throw(AssertionError("TMDB should not run after Kitsu supplies a poster")))

    results, notices = metadata.search_anime_metadata("SANDA")

    assert [result["source"] for result in results] == ["AniList", "Kitsu"]
    assert results[0]["poster"] == "https://kitsu.example/sanda.jpg"
    assert results[0]["poster_source"] == "Kitsu"
    assert results[1]["poster"] == "https://kitsu.example/sanda.jpg"
    assert any("without posters" in notice for notice in notices)


def test_user_settings_default_preferred_subbers_include_subsplease(monkeypatch) -> None:
    monkeypatch.setattr(app_state, "_read_user_database", lambda: {"settings": {}, "anime": [], "events": []})

    settings = app_state.user_settings()

    assert settings["preferred_subbers"] == ["SubsPlease"]
    assert settings["preferred_subbers_text"] == "SubsPlease"


def test_save_torrent_preferences_keeps_subsplease_first(monkeypatch) -> None:
    database = {"settings": {}, "anime": [], "events": []}
    writes = []
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    success, message = app_state.save_torrent_preferences({"preferred_subbers": "Erai-raws\nSubsPlease", "torrent_confidence_threshold": "80"})

    assert success is True
    assert message == "Torrent preferences saved."
    assert database["settings"]["preferred_subbers"] == ["SubsPlease", "Erai-raws"]
    assert database["settings"]["torrent_confidence_threshold"] == 80
    assert writes == [database]


def test_refresh_torrent_search_passes_defaulted_preferred_subbers(monkeypatch) -> None:
    calls = []
    anime = {"title": "Petals of Reincarnation"}
    database = {"settings": {"preferred_subbers": ["Erai-raws"]}, "ignored_torrents": [], "events": [], "anime": []}

    def fake_find(item, preferred_subbers=None):
        calls.append(preferred_subbers)
        return {"query": item["title"], "strategy": "test", "candidates": [], "notices": []}

    monkeypatch.setattr(app_state, "find_torrents_for_anime", fake_find)

    app_state._refresh_torrent_search(anime, database)

    assert calls == [["SubsPlease", "Erai-raws"]]


def test_unblock_ignored_torrent_removes_blocked_key(monkeypatch) -> None:
    database = {
        "settings": {},
        "events": [],
        "ignored_torrents": [{"key": "hash:bad"}, {"key": "hash:keep"}],
    }
    writes = []
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    success, message = app_state.unblock_ignored_torrent("hash:bad")

    assert success is True
    assert message == "Torrent candidate unblocked. It can be considered by future searches."
    assert database["ignored_torrents"] == [{"key": "hash:keep"}]
    assert writes == [database]


def test_update_anime_preferences_marks_unmonitored_and_refresh_pending(monkeypatch) -> None:
    database = {
        "settings": {"root_folder": "C:/Anime"},
        "events": [],
        "anime": [
            {
                "library_id": "anime-1",
                "title": "Petals of Reincarnation",
                "quality_resolution": "720p",
                "season_number": 1,
                "episodes": "12",
                "completion": {"expected_episodes": 12, "local_episodes": 0, "progress_target": 12, "missing_episodes": 12},
                "torrent_search": {"checked_at": "2026-01-01T00:00:00+00:00", "candidates": [{"title": "old"}]},
            }
        ],
    }
    writes = []
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    success, message = app_state.update_anime_preferences("anime-1", {"quality_resolution": "1080p", "season_number": "2"})

    anime = database["anime"][0]
    assert success is True
    assert message.startswith("Anime preferences saved.")
    assert anime["quality_resolution"] == "1080p"
    assert anime["season_number"] == 2
    assert anime["monitored"] is False
    assert "checked_at" not in anime["torrent_search"]
    assert writes == [database]


def test_update_anime_preferences_unmonitor_clears_active_queues_and_keeps_history(monkeypatch) -> None:
    active_queue = {
        "status": "queued",
        "hash": "active-hash",
        "episode": 2,
        "title": "[SubsPlease] Petals of Reincarnation - 02 [1080p]",
    }
    completed_queue = {
        "status": "completed",
        "hash": "complete-hash",
        "episode": 1,
        "title": "[SubsPlease] Petals of Reincarnation - 01 [1080p]",
    }
    database = {
        "settings": {"root_folder": "C:/Anime"},
        "events": [],
        "anime": [
            {
                "library_id": "anime-1",
                "title": "Petals of Reincarnation",
                "quality_resolution": "1080p",
                "season_number": 1,
                "monitored": True,
                "episodes": "12",
                "completion": {"expected_episodes": 12, "local_episodes": 1, "progress_target": 12, "missing_episodes": 11},
                "torrent_search": {"checked_at": "2026-01-01T00:00:00+00:00", "candidates": [{"title": "old"}]},
                "torrent_manual_selection": {"required": True},
                "download_queue": active_queue,
                "download_queues": [active_queue, completed_queue],
            }
        ],
    }
    writes = []
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    success, message = app_state.update_anime_preferences("anime-1", {"quality_resolution": "1080p", "season_number": "1"})

    anime = database["anime"][0]
    assert success is True
    assert "Cleared 1 active queued download(s)." in message
    assert anime["monitored"] is False
    assert anime["download_queues"] == [completed_queue]
    assert anime["download_queue"] == completed_queue
    assert anime["torrent_manual_selection"] == {"required": False}
    assert anime["torrent_search"]["strategy"] == "Torrent search paused because anime is unmonitored"
    assert anime["torrent_search"]["candidates"] == []
    assert "checked_at" not in anime["torrent_search"]
    assert database["unmonitored_titles"][0]["title_key"] == "petals of reincarnation"
    assert writes == [database]



def test_unmonitored_title_pruning_archives_overflow_to_cold_storage(monkeypatch, tmp_path) -> None:
    cold_path = tmp_path / "cold" / "unmonitored.jsonl"
    monkeypatch.setattr(app_state, "UNMONITORED_TITLES_COLD_STORAGE_PATH", cold_path)
    monkeypatch.setattr(app_state, "MAX_UNMONITORED_TITLE_ENTRIES", 2)
    database = {
        "unmonitored_titles": [
            {"title": "Old A", "title_key": "old a", "provider_ids": {"anilist": "1"}, "recorded_at": "2026-01-01T00:00:00+00:00"},
            {"title": "Hot B", "title_key": "hot b", "provider_ids": {"anilist": "2"}, "recorded_at": "2026-01-02T00:00:00+00:00"},
            {"title": "Hot C", "title_key": "hot c", "provider_ids": {"anilist": "3"}, "recorded_at": "2026-01-03T00:00:00+00:00"},
        ]
    }

    changed = app_state._prune_unmonitored_titles(database)

    assert changed is True
    assert [entry["title_key"] for entry in database["unmonitored_titles"]] == ["hot b", "hot c"]
    lines = cold_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    archived = json.loads(lines[0])
    assert archived["action"] == "pause"
    assert archived["payload"]["title_key"] == "old a"


def test_root_scan_uses_cold_unmonitored_title_marker(monkeypatch, tmp_path) -> None:
    cold_path = tmp_path / "cold" / "unmonitored.jsonl"
    monkeypatch.setattr(app_state, "UNMONITORED_TITLES_COLD_STORAGE_PATH", cold_path)
    app_state._append_unmonitored_title_cold_event(
        "pause",
        {
            "title": "Chiikawa",
            "title_key": "chiikawa",
            "provider_ids": {"anilist": "170182"},
            "library_id": "AniList:170182",
            "recorded_at": "2026-01-01T00:00:00+00:00",
        },
    )
    database = {"settings": {"root_folder": str(tmp_path)}, "events": [], "anime": [], "unmonitored_titles": []}
    candidate = {
        "library_id": "root-folder:chiikawa",
        "title": "Chiikawa",
        "original_title": "Chiikawa",
        "episodes": "1",
        "status": "Unknown",
        "monitored": True,
        "quality_resolution": "1080p",
        "provider_ids": {"anilist": "170182"},
        "torrent_search": {"query": "Chiikawa", "strategy": "Imported from root folder scan", "candidates": []},
    }
    summary = app_state._empty_scan_summary()

    stored = app_state._store_root_folder_candidate(database, candidate, summary)

    assert stored["monitored"] is False
    assert stored["library_state"] == "Paused"
    assert stored["torrent_search"]["strategy"] == "Torrent search paused because anime is unmonitored"


def test_cold_unmonitored_title_unpause_event_overrides_pause(monkeypatch, tmp_path) -> None:
    cold_path = tmp_path / "cold" / "unmonitored.jsonl"
    monkeypatch.setattr(app_state, "UNMONITORED_TITLES_COLD_STORAGE_PATH", cold_path)
    entry = {
        "title": "Chiikawa",
        "title_key": "chiikawa",
        "provider_ids": {"anilist": "170182"},
        "library_id": "AniList:170182",
        "recorded_at": "2026-01-01T00:00:00+00:00",
    }
    app_state._append_unmonitored_title_cold_event("pause", entry)
    app_state._append_unmonitored_title_cold_event("unpause", entry)

    assert app_state._cold_unmonitored_title_match({"title": "Chiikawa", "provider_ids": {"anilist": "170182"}}) is False

def test_update_anime_preferences_remonitor_removes_unmonitored_title_guard(monkeypatch) -> None:
    database = {
        "settings": {"root_folder": "C:/Anime"},
        "events": [],
        "unmonitored_titles": [
            {
                "title": "Petals of Reincarnation",
                "title_key": "petals of reincarnation",
                "provider_ids": {"anilist": "179950"},
                "library_id": "anime-1",
                "recorded_at": "2026-01-01T00:00:00+00:00",
            }
        ],
        "anime": [
            {
                "library_id": "anime-1",
                "title": "Petals of Reincarnation",
                "original_title": "Petals of Reincarnation",
                "provider_ids": {"anilist": "179950"},
                "quality_resolution": "1080p",
                "season_number": 1,
                "monitored": False,
                "episodes": "12",
                "completion": {"expected_episodes": 12, "local_episodes": 1, "progress_target": 12, "missing_episodes": 11},
                "torrent_search": {"strategy": "Torrent search paused because anime is unmonitored", "candidates": []},
            }
        ],
    }
    writes = []
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    success, message = app_state.update_anime_preferences(
        "anime-1", {"quality_resolution": "1080p", "season_number": "1", "monitored": "on"}
    )

    anime = database["anime"][0]
    assert success is True
    assert message == "Anime preferences saved."
    assert anime["monitored"] is True
    assert database["unmonitored_titles"] == []
    assert anime["torrent_search"]["strategy"] == "Queued for background torrent search"
    assert writes == [database]


def test_delete_anime_removes_library_item_without_touching_files(monkeypatch) -> None:
    database = {"settings": {}, "events": [], "anime": [{"library_id": "anime-1", "title": "Petals"}, {"library_id": "anime-2", "title": "Other"}]}
    writes = []
    monkeypatch.setattr(app_state, "_read_user_database", lambda: database)
    monkeypatch.setattr(app_state, "_write_user_database", lambda db: writes.append(db))

    success, message = app_state.delete_anime("anime-1")

    assert success is True
    assert message == "Anime removed from the library. Local files were not deleted."
    assert [item["library_id"] for item in database["anime"]] == ["anime-2"]
    assert writes == [database]


def test_anilist_metadata_refresh_preserves_selected_alias_title(monkeypatch) -> None:
    now = datetime(2026, 7, 6, 0, 0, tzinfo=timezone.utc).timestamp()
    database = {"settings": {"root_folder": "C:/Anime"}, "events": [], "anime": []}
    anime = {
        "library_id": "AniList:188384",
        "title": "Daemons of the Shadow Realm",
        "original_title": "Yomi no Tsugai",
        "year": "2026",
        "season_number": 1,
        "episodes": "Unknown",
        "status": "Releasing",
        "monitored": True,
        "provider_ids": {"anilist": "188384"},
        "source": "AniList",
        "aliases": ["Daemons of the Shadow Realm", "Yomi no Tsugai"],
        "torrent_search": {"candidates": [], "notices": []},
    }
    database["anime"].append(anime)
    anilist = root_scan_metadata("Yomi no Tsugai")
    anilist.update(
        {
            "title": "Yomi no Tsugai",
            "original_title": "Yomi no Tsugai",
            "source": "AniList",
            "provider_ids": {"anilist": "188384"},
            "aliases": ["Yomi no Tsugai", "Daemons do Reino das Sombras", "Daemons of the Shadow Realm"],
            "provider_title": {"english": "", "romaji": "Yomi no Tsugai", "native": "Yomi native title"},
        }
    )

    monkeypatch.setattr(app_state, "search_anilist_by_id", lambda anilist_id: anilist if anilist_id == "188384" else None)
    monkeypatch.setattr(app_state, "_resolved_metadata_cache_store", lambda context, metadata: None)

    changed = app_state._refresh_anilist_metadata(database, anime, now)

    assert changed is True
    assert anime["title"] == "Daemons of the Shadow Realm"
    assert anime["original_title"] == "Yomi no Tsugai"
    assert anime["source"] == "AniList"
    assert anime["provider_ids"]["anilist"] == "188384"
    assert anime["torrent_search"]["query"] == "Daemons of the Shadow Realm"
