from __future__ import annotations

import threading
from typing import Any

import pytest

from nyaarr import app_state, torrent_finder


def release(group: str, episode: int, *, seeders: int = 10, downloads: int = 100) -> dict[str, Any]:
    title = f"[{group}] Petals of Reincarnation - {episode:02d} [1080p]"
    return {
        "title": title,
        "detail_url": f"https://nyaa.si/view/{group}-{episode}",
        "torrent_url": f"https://nyaa.si/download/{group}-{episode}.torrent",
        "guid": f"https://nyaa.si/view/{group}-{episode}",
        "published": "",
        "seeders": seeders,
        "leechers": 0,
        "downloads": downloads,
        "infohash": f"{group}-{episode}",
        "category": "Anime - English-translated",
        "category_id": "1_2",
        "size": "1.0 GiB",
        "size_bytes": 1024**3,
        "trusted": "No",
        "remake": "No",
        "release_group": group,
        "release_kind": "episode",
        "episode": episode,
        "source_kind": "web",
        "resolution": 1080,
    }


def batch_release(group: str, *, seeders: int = 50, downloads: int = 500) -> dict[str, Any]:
    title = f"[{group}] Petals of Reincarnation Complete [1080p]"
    return {
        "title": title,
        "detail_url": f"https://nyaa.si/view/{group}-batch",
        "torrent_url": f"https://nyaa.si/download/{group}-batch.torrent",
        "guid": f"https://nyaa.si/view/{group}-batch",
        "published": "",
        "seeders": seeders,
        "leechers": 0,
        "downloads": downloads,
        "infohash": f"{group}-batch",
        "category": "Anime - English-translated",
        "category_id": "1_2",
        "size": "60.0 GiB",
        "size_bytes": 60 * 1024**3,
        "trusted": "No",
        "remake": "No",
        "release_group": group,
        "release_kind": "batch",
        "episode": None,
        "source_kind": "web",
        "resolution": 1080,
    }


def anime(*, local_episodes: int = 0, progress_target: int = 5) -> dict[str, Any]:
    return {
        "title": "Petals of Reincarnation",
        "episodes": str(progress_target),
        "quality_resolution": "1080p",
        "airing_episode": str(progress_target + 1),
        "completion": {
            "local_episodes": local_episodes,
            "progress_target": progress_target,
            "expected_episodes": progress_target,
        },
    }


def test_episode_selection_requires_one_group_to_cover_all_missing_episodes() -> None:
    releases = [
        release("FastGroup", 5, seeders=200),
        *(release("SteadySubs", episode, seeders=20) for episode in range(1, 6)),
    ]

    candidates = torrent_finder._select_candidates(releases, anime())

    assert [candidate["episode"] for candidate in candidates] == [1, 2, 3, 4, 5]
    assert {candidate["release_group"] for candidate in candidates} == {"SteadySubs"}


def test_episode_selection_does_not_mix_subbers_for_missing_episodes() -> None:
    releases = [
        release("Alpha", 1, seeders=100),
        release("Beta", 2, seeders=100),
        release("Alpha", 2, seeders=10),
        release("Beta", 1, seeders=10),
    ]

    candidates = torrent_finder._select_candidates(releases, anime(progress_target=2))

    assert [candidate["episode"] for candidate in candidates] == [1, 2]
    assert len({candidate["release_group"] for candidate in candidates}) == 1


def test_find_torrents_loads_episode_searches_before_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "Petals of Reincarnation":
            return [release("SteadySubs", 5, seeders=30)]
        episode = int(query.rsplit(" ", 1)[1])
        return [release("SteadySubs", episode, seeders=30)]

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(anime())

    assert calls == [
        "Petals of Reincarnation",
        "Petals of Reincarnation 01",
        "Petals of Reincarnation 02",
        "Petals of Reincarnation 03",
        "Petals of Reincarnation 04",
        "Petals of Reincarnation 05",
    ]
    assert [candidate["episode"] for candidate in result["candidates"]] == [1, 2, 3, 4, 5]
    assert "Loaded 4 episode-specific RSS candidate(s) before selection." in result["notices"]



def test_large_backlog_tries_batch_before_episode_fanout(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    item = anime(progress_target=12)

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "Petals of Reincarnation":
            return []
        if query == "Petals of Reincarnation batch":
            return [batch_release("SteadySubs", seeders=40)]
        if query == "Petals of Reincarnation complete":
            return []
        raise AssertionError(f"episode fan-out should have been skipped: {query}")

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "LARGE_BACKLOG_BATCH_SEARCH_THRESHOLD", 6)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(item)

    assert calls == ["Petals of Reincarnation", "Petals of Reincarnation batch", "Petals of Reincarnation complete"]
    assert result["candidates"][0]["release_kind"] == "batch"
    assert "Skipped episode-specific RSS fan-out because a compatible batch candidate was found." in result["notices"]


def test_episode_search_queries_use_parallel_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    thread_names = []

    def fake_search(query: str) -> list[dict[str, Any]]:
        if query == "Petals of Reincarnation":
            return []
        thread_names.append(threading.current_thread().name)
        episode = int(query.rsplit(" ", 1)[1])
        return [release("SteadySubs", episode, seeders=30)]

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 3)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(anime(progress_target=4))

    assert [candidate["episode"] for candidate in result["candidates"]] == [1, 2, 3, 4]
    assert any(name.startswith("nyaa-rss") for name in thread_names)

def test_dispatch_release_selection_skips_episode_candidates_that_are_no_longer_missing() -> None:
    database = {"settings": {"torrent_confidence_threshold": 0, "preferred_subbers": []}, "ignored_torrents": []}
    item = anime(local_episodes=1, progress_target=2)
    candidates = [release("SteadySubs", 1, seeders=500), release("SteadySubs", 2, seeders=5)]

    selected = app_state._selected_download_release(candidates, database, item)

    assert selected is not None
    assert selected["episode"] == 2



def test_rezero_style_ordinal_season_and_episode_title_parse() -> None:
    title = "[Erai-raws] Re Zero kara Hajimeru Isekai Seikatsu 4th Season - 11 [1080p][Multiple Subtitle][ABC123].mkv"

    assert torrent_finder._torrent_season_number(title) == 4
    assert torrent_finder._episode_number(title) == 11


def test_episode_number_parses_season_shorthand_dash_episode() -> None:
    title = "[EMBER] Mato Seihei no Slave S2 - 01.mkv"

    assert torrent_finder._torrent_season_number(title) == 2
    assert torrent_finder._episode_number(title) == 1


def test_episode_number_parses_versioned_sxxe_episode() -> None:
    assert torrent_finder._episode_number("[Judas] SAKAMOTO DAYS - S01E01v2.mkv") == 1


def test_episode_number_parses_dash_episode_before_extension() -> None:
    assert torrent_finder._episode_number("[UsifRenegade] The Law of Ueki - 01.mkv") == 1


def test_find_torrents_uses_successful_alternate_title_for_episode_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    anime_item = anime(progress_target=2)
    anime_item.update(
        {
            "title": "Re:ZERO -Starting Life in Another World- Season 4",
            "original_title": "Re Zero kara Hajimeru Isekai Seikatsu 4th Season",
            "season_number": 4,
        }
    )

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "Re:ZERO -Starting Life in Another World- Season 4":
            return []
        episode = 1 if query == "Re Zero kara Hajimeru Isekai Seikatsu 4th Season" else int(query.rsplit(" ", 1)[1])
        candidate = release("Erai-raws", episode, seeders=30)
        candidate["title"] = f"[Erai-raws] Re Zero kara Hajimeru Isekai Seikatsu 4th Season - {episode:02d} [1080p]"
        return [candidate]

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(anime_item)

    assert calls == [
        "Re:ZERO -Starting Life in Another World- Season 4",
        "Re Zero kara Hajimeru Isekai Seikatsu 4th Season",
        "Re Zero kara Hajimeru Isekai Seikatsu 4th Season 01",
        "Re Zero kara Hajimeru Isekai Seikatsu 4th Season 02",
    ]
    assert result["query"] == "Re Zero kara Hajimeru Isekai Seikatsu 4th Season"
    assert [candidate["episode"] for candidate in result["candidates"]] == [1, 2]




def test_find_torrents_continues_alias_search_for_existing_local_subber(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    anime_item = anime(local_episodes=9, progress_target=11)
    anime_item.update(
        {
            "title": "SHIBOYUGI: Playing Death Games to Put Food on the Table",
            "original_title": "Shibou Yuugi de Meshi wo Kuu.",
            "metadata_search_titles": [
                "SHIBOYUGI: Playing Death Games to Put Food on the Table",
                "Shibou Yuugi de Meshi wo Kuu.",
            ],
            "episode_files": [
                f"/anime/Shibou Yuugi de Meshi wo Kuu/[SubsPlease] Shibou Yuugi de Meshi wo Kuu. - {episode:02d} (1080p).mkv"
                for episode in range(1, 10)
            ],
        }
    )

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "SHIBOYUGI: Playing Death Games to Put Food on the Table":
            candidate = release("Unknown", 10, seeders=100)
            candidate["title"] = "SHIBOYUGI Playing Death Games to Put Food on the Table S01E10 1080p WEB-DL H 264-VARYG"
            candidate["release_group"] = "VARYG"
            return [candidate]
        if query == "Shibou Yuugi de Meshi wo Kuu.":
            candidate = release("SubsPlease", 10, seeders=10)
            candidate["title"] = "[SubsPlease] Shibou Yuugi de Meshi wo Kuu. - 10 (1080p)"
            return [candidate]
        episode = int(query.rsplit(" ", 1)[1])
        candidate = release("SubsPlease", episode, seeders=10)
        candidate["title"] = f"[SubsPlease] Shibou Yuugi de Meshi wo Kuu. - {episode:02d} (1080p)"
        return [candidate]

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(anime_item)

    assert calls == [
        "SHIBOYUGI: Playing Death Games to Put Food on the Table",
        "Shibou Yuugi de Meshi wo Kuu.",
        "Shibou Yuugi de Meshi wo Kuu. 10",
        "Shibou Yuugi de Meshi wo Kuu. 11",
    ]
    assert result["query"] == "Shibou Yuugi de Meshi wo Kuu."
    assert [candidate["episode"] for candidate in result["candidates"]] == [10, 11]
    assert {candidate["release_group"] for candidate in result["candidates"]} == {"SubsPlease"}

def test_find_torrents_uses_alias_title_for_search_when_primary_title_misses(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    anime_item = anime(progress_target=1)
    anime_item.update(
        {
            "title": "Petals of Reincarnation",
            "aliases": ["Reincarnation no Kaben"],
        }
    )

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "Reincarnation no Kaben":
            candidate = release("SubsPlease", 1, seeders=20)
            candidate["title"] = "[SubsPlease] Reincarnation no Kaben - 01 [1080p]"
            return [candidate]
        return []

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(anime_item)

    assert calls[:2] == ["Petals of Reincarnation", "Reincarnation no Kaben"]
    assert result["query"] == "Reincarnation no Kaben"
    assert result["candidates"][0]["episode"] == 1
    assert "Used alternate title search: Reincarnation no Kaben." in result["notices"]

def test_episode_selection_keeps_one_best_release_per_episode_before_candidate_cap() -> None:
    releases = []
    for episode in range(1, 13):
        releases.extend(release("VARYG", episode, seeders=seeders, downloads=seeders * 10) for seeders in range(1, 4))

    candidates = torrent_finder._select_candidates(releases, anime(progress_target=12))

    assert [candidate["episode"] for candidate in candidates] == list(range(1, 13))
    assert all(candidate["seeders"] == 3 for candidate in candidates)



def test_release_group_parses_scene_style_suffix_group() -> None:
    assert torrent_finder._release_group(
        "Example Anime S01E04 1080p WEB-DL AAC2.0 x265-SUBBER.mkv"
    ) == "SUBBER"


def test_release_group_parses_codec_suffix_before_trailing_notes() -> None:
    assert torrent_finder._release_group(
        "Petals of Reincarnation S01E12 Till My Voice is Heard 1080p AMZN WEB-DL DDP2.0 H 264-VARYG (Reincarnation no Kaben, Multi-Subs)"
    ) == "VARYG"


def test_episode_selection_prefers_subber_from_existing_local_files() -> None:
    item = anime(local_episodes=28, progress_target=29)
    item["episode_files"] = [
        f"/anime/Digimon Beatbreak/[SubsPlease] Digimon Beatbreak - {episode:02d} [1080p].mkv"
        for episode in range(1, 29)
    ]
    releases = [
        release("HighSeeds", 29, seeders=500),
        release("SubsPlease", 29, seeders=5),
    ]

    candidates = torrent_finder._select_candidates(releases, item)

    assert [candidate["episode"] for candidate in candidates] == [29]
    assert candidates[0]["release_group"] == "SubsPlease"

def test_episode_selection_keeps_suffix_subber_consistent() -> None:
    releases = []
    for episode in range(1, 4):
        title = f"Petals of Reincarnation S01E{episode:02d} 1080p WEB-DL AAC2.0 x265-VARYG.mkv"
        item = release("Unknown", episode, seeders=20)
        item["title"] = title
        item["release_group"] = torrent_finder._release_group(title)
        releases.append(item)
    beta = release("Other", 1, seeders=100)
    releases.append(beta)

    candidates = torrent_finder._select_candidates(releases, anime(progress_target=3))

    assert [candidate["episode"] for candidate in candidates] == [1, 2, 3]
    assert {candidate["release_group"] for candidate in candidates} == {"VARYG"}


def test_missing_episodes_use_parsed_local_episode_files() -> None:
    item = anime(local_episodes=9, progress_target=12)
    item["episode_files"] = [
        f"/anime/Petals.of.Reincarnation.S01E{episode:02d}.1080p.mkv"
        for episode in (3, 4, 5, 6, 7, 8, 9, 11, 12)
    ]

    assert torrent_finder._missing_episodes(item) == {1, 2, 10}


def test_episode_selection_allows_best_partial_group_when_full_missing_coverage_is_unavailable() -> None:
    releases = [
        release("ToonsHub", 10, seeders=57),
        release("Other", 10, seeders=10),
    ]

    candidates = torrent_finder._select_candidates(releases, anime(local_episodes=9, progress_target=12) | {
        "episode_files": [
            f"/anime/Petals.of.Reincarnation.S01E{episode:02d}.1080p.mkv"
            for episode in (3, 4, 5, 6, 7, 8, 9, 11, 12)
        ]
    })

    assert [candidate["episode"] for candidate in candidates] == [10]
    assert candidates[0]["release_group"] == "ToonsHub"


def test_completed_anime_does_not_plan_filename_gap_searches() -> None:
    item = anime(local_episodes=12, progress_target=12)
    item["library_state"] = "Completed"
    item["episode_files"] = [f"/anime/Show.S01E{episode:02d}.mkv" for episode in range(13, 25)]

    assert torrent_finder._missing_episodes(item) == set()


def test_simple_title_requires_exact_series_identity() -> None:
    assert torrent_finder._title_matches("Monster", "[SomeGroup] Monster - 01 [1080p]") is True
    assert torrent_finder._title_matches("Monster", "[SomeGroup] Monster Musume no Iru Nichijou - 01 [1080p]") is False
    assert torrent_finder._title_matches("Monster", "[SomeGroup] Pocket Monsters - 01 [1080p]") is False


def test_find_torrents_flags_no_candidates_for_manual_intervention(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", lambda query: [])

    result = torrent_finder.find_torrents_for_anime(anime(progress_target=2))

    assert result["candidates"] == []
    assert "No batch or per-episode RSS candidates were found." in result["notices"]



def test_same_subber_batch_fallback_replaces_stale_or_low_seed_episode_plan() -> None:
    item = anime(local_episodes=56, progress_target=59)
    item["episode_files"] = [
        f"/anime/Petals/[SteadySubs] Petals of Reincarnation - {episode:02d} [1080p].mkv"
        for episode in range(1, 57)
    ]
    item["download_queues"] = [
        {
            "status": "stalled",
            "release_kind": "episode",
            "release_group": "SteadySubs",
            "episode": 57,
            "progress": 0,
            "queued_at": "2000-01-01T00:00:00+00:00",
        }
    ]
    releases = [
        release("SteadySubs", 57, seeders=0),
        release("SteadySubs", 58, seeders=1),
        release("SteadySubs", 59, seeders=1),
        batch_release("SteadySubs", seeders=40),
    ]

    candidates = torrent_finder._select_candidates(releases, item)

    assert len(candidates) == 1
    assert candidates[0]["release_kind"] == "batch"
    assert candidates[0]["release_group"] == "SteadySubs"
    assert candidates[0]["batch_fallback_episodes"] == [57, 58, 59]
    assert "same-subber batch fallback" in torrent_finder._selection_strategy(candidates)


def test_batch_fallback_does_not_switch_to_different_subber() -> None:
    item = anime(local_episodes=56, progress_target=57)
    item["episode_files"] = [
        f"/anime/Petals/[SteadySubs] Petals of Reincarnation - {episode:02d} [1080p].mkv"
        for episode in range(1, 57)
    ]
    releases = [release("SteadySubs", 57, seeders=0), batch_release("OtherSubs", seeders=100)]

    candidates = torrent_finder._select_candidates(releases, item)

    assert [candidate["episode"] for candidate in candidates] == [57]
    assert candidates[0]["release_group"] == "SteadySubs"


def test_find_torrents_loads_same_subber_batch_fallback_searches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    item = anime(local_episodes=2, progress_target=3)
    item["episode_files"] = [
        f"/anime/Petals/[SteadySubs] Petals of Reincarnation - {episode:02d} [1080p].mkv"
        for episode in range(1, 3)
    ]
    item["download_queues"] = [
        {
            "status": "stalled",
            "release_kind": "episode",
            "release_group": "SteadySubs",
            "episode": 3,
            "progress": 0,
            "queued_at": "2000-01-01T00:00:00+00:00",
        }
    ]

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query == "Petals of Reincarnation 03":
            return [release("SteadySubs", 3, seeders=0)]
        if query == "Petals of Reincarnation batch":
            return [batch_release("SteadySubs", seeders=50)]
        return []

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(item)

    assert calls[:3] == [
        "Petals of Reincarnation",
        "Petals of Reincarnation 03",
        "Petals of Reincarnation batch",
    ]
    assert result["candidates"][0]["release_kind"] == "batch"
    assert result["candidates"][0]["batch_fallback_episodes"] == [3]
    assert "Loaded 1 same-subber batch fallback candidate(s) before selection." in result["notices"]


def test_batch_fallback_candidate_scores_through_normal_confidence() -> None:
    item = anime(local_episodes=56, progress_target=57)
    item["episode_files"] = [
        f"/anime/Petals/[SteadySubs] Petals of Reincarnation - {episode:02d} [1080p].mkv"
        for episode in range(1, 57)
    ]
    candidate = batch_release("SteadySubs", seeders=40)
    candidate["batch_fallback_episodes"] = [57]

    score, reasons = app_state._torrent_candidate_confidence(
        candidate,
        {"settings": {"preferred_subbers": []}},
        item,
    )

    assert score >= 70
    assert "same-subber batch can target stalled or low-seed missing episodes" in reasons


def test_find_torrents_tries_preferred_subber_query_before_generic(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    item = anime(progress_target=1)

    def fake_search(query: str) -> list[dict[str, Any]]:
        calls.append(query)
        if query in {"SubsPlease Petals of Reincarnation", "SubsPlease Petals of Reincarnation 01"}:
            return [release("SubsPlease", 1, seeders=5)]
        return []

    monkeypatch.setattr(torrent_finder, "NYAA_RSS_SEARCH_WORKERS", 1)
    monkeypatch.setattr(torrent_finder, "search_nyaa_rss", fake_search)

    result = torrent_finder.find_torrents_for_anime(item, ["SubsPlease"])

    assert calls[0] == "SubsPlease Petals of Reincarnation"
    assert result["candidates"][0]["release_group"] == "SubsPlease"


def test_episode_selection_prefers_configured_subber_without_local_history() -> None:
    releases = [release("HighSeeds", 1, seeders=500), release("SubsPlease", 1, seeders=5)]

    candidates = torrent_finder._select_candidates(releases, anime(progress_target=1), ["SubsPlease"])

    assert [candidate["release_group"] for candidate in candidates] == ["SubsPlease"]
