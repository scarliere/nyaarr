from __future__ import annotations

import concurrent.futures
import os
import re
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


NYAA_RSS_URL = "https://nyaa.si/"
NYAA_NAMESPACE = "{https://nyaa.si/xmlns/nyaa}"
HTTP_TIMEOUT_SECONDS = float(os.environ.get("NYAARR_NYAA_HTTP_TIMEOUT_SECONDS", "8"))
NYAA_RSS_SEARCH_WORKERS = min(16, max(1, int(os.environ.get("NYAARR_NYAA_RSS_SEARCH_WORKERS", "8"))))
NYAA_RSS_CACHE_TTL_SECONDS = int(os.environ.get("NYAARR_NYAA_RSS_CACHE_TTL_SECONDS", "300"))
NYAA_RSS_CACHE_MAX_ENTRIES = max(0, int(os.environ.get("NYAARR_NYAA_RSS_CACHE_MAX_ENTRIES", "256")))
NYAA_MAX_EPISODE_SEARCH_QUERIES = max(0, int(os.environ.get("NYAARR_NYAA_MAX_EPISODE_SEARCH_QUERIES", "72")))
LARGE_BACKLOG_BATCH_SEARCH_THRESHOLD = int(os.environ.get("NYAARR_LARGE_BACKLOG_BATCH_SEARCH_THRESHOLD", "6"))
_RSS_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_RSS_CACHE_LOCK = threading.Lock()
LOW_SEED_BATCH_FALLBACK_SEEDERS = int(os.environ.get("NYAARR_LOW_SEED_BATCH_FALLBACK_SEEDERS", "3"))
STALLED_TORRENT_BATCH_FALLBACK_SECONDS = int(os.environ.get("NYAARR_STALLED_TORRENT_BATCH_FALLBACK_SECONDS", str(6 * 60 * 60)))


class TorrentFinderError(RuntimeError):
    pass


def episode_number_from_title(title: str) -> int | None:
    return _episode_number(title)

def release_group_from_title(title: str) -> str:
    return _release_group(title)


def find_torrents_for_anime(anime: dict[str, Any], preferred_subbers: list[str] | None = None) -> dict[str, Any]:
    search_titles = _search_titles(anime)
    search_title = search_titles[0] if search_titles else ""
    season_number = _selected_season_number(anime)
    preferred_group = _local_release_group_preference(anime)
    preferred_groups = _release_group_preferences(preferred_group, preferred_subbers)
    search_preferred_groups = _release_group_preferences("", preferred_subbers)
    if not search_title:
        return {
            "query": "",
            "strategy": "No title available",
            "candidates": [],
            "notices": ["Torrent finder skipped because no title was available."],
        }

    notices: list[str] = []
    related_releases: list[dict[str, Any]] = []
    first_related_releases: list[dict[str, Any]] = []
    first_matched_search_title = ""
    matched_search_title = search_title
    for index, candidate_title in enumerate(search_titles):
        for query in _initial_search_queries(candidate_title, search_preferred_groups):
            try:
                releases = search_nyaa_rss(query)
            except TorrentFinderError as exc:
                if index == 0 and query == candidate_title:
                    return {
                        "query": search_title,
                        "strategy": "RSS search failed",
                        "candidates": [],
                        "notices": [str(exc)],
                    }
                notices.append(str(exc))
                continue

            related_releases = [
                release
                for release in releases
                if _title_matches(candidate_title, release["title"])
                and _season_matches(season_number, release["title"])
            ]
            if not related_releases:
                continue

            if not first_related_releases:
                first_related_releases = related_releases
                first_matched_search_title = candidate_title
            matched_search_title = candidate_title
            if candidate_title != search_title:
                notices.append(f"Used alternate title search: {candidate_title}.")
            if query != candidate_title:
                notices.append(f"Used preferred subber search: {query}.")
            if preferred_group and not any(
                str(release.get("release_group") or "").casefold() == preferred_group.casefold()
                for release in related_releases
            ):
                notices.append(
                    f"Continuing alternate title searches because {candidate_title} did not find {preferred_group} releases."
                )
                related_releases = []
                continue
            break
        if related_releases:
            break

    if not related_releases and first_related_releases:
        related_releases = first_related_releases
        matched_search_title = first_matched_search_title or search_title

    missing_episodes = _missing_episodes(anime)
    if missing_episodes:
        if _should_try_large_backlog_batch_search(anime, related_releases, missing_episodes):
            before_batch_count = len(related_releases)
            related_releases = _load_batch_search_releases(
                matched_search_title,
                season_number,
                related_releases,
                preferred_group,
                notices,
            )
            added_batch_count = len(related_releases) - before_batch_count
            if added_batch_count:
                notices.append(f"Loaded {added_batch_count} upfront batch RSS candidate(s) before episode search.")
        if not _has_compatible_batch_candidate(anime, related_releases):
            before_count = len(related_releases)
            related_releases = _load_episode_search_releases(
                matched_search_title,
                season_number,
                related_releases,
                missing_episodes,
                notices,
                search_preferred_groups,
            )
            added_count = len(related_releases) - before_count
            if added_count:
                notices.append(f"Loaded {added_count} episode-specific RSS candidate(s) before selection.")
        else:
            notices.append("Skipped episode-specific RSS fan-out because a compatible batch candidate was found.")
        if _should_load_batch_fallback_searches(anime, related_releases, missing_episodes):
            before_batch_count = len(related_releases)
            related_releases = _load_batch_search_releases(
                matched_search_title,
                season_number,
                related_releases,
                preferred_group,
                notices,
            )
            added_batch_count = len(related_releases) - before_batch_count
            if added_batch_count:
                notices.append(f"Loaded {added_batch_count} same-subber batch fallback candidate(s) before selection.")

    candidates = _select_candidates(related_releases, anime, preferred_groups)
    strategy = _selection_strategy(candidates)
    if not candidates:
        notices.append("No batch or per-episode RSS candidates were found.")

    return {
        "query": matched_search_title,
        "strategy": strategy,
        "candidates": candidates,
        "notices": notices,
    }
def _search_titles(anime: dict[str, Any]) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    for value in _anime_title_values(anime):
        title = str(value or "").strip()
        key = title.casefold()
        if title and key not in seen:
            titles.append(title)
            seen.add(key)
    return titles


def _anime_title_values(anime: dict[str, Any]) -> list[Any]:
    values: list[Any] = [
        anime.get("title"),
        anime.get("original_title"),
        anime.get("romaji_title"),
        anime.get("english_title"),
        anime.get("native_title"),
    ]
    for key in ("metadata_search_titles", "aliases"):
        titles = anime.get(key)
        if isinstance(titles, list):
            values.extend(titles)
    provider_title = anime.get("provider_title")
    if isinstance(provider_title, dict):
        values.extend(provider_title.get(key) for key in ("romaji", "english", "native"))
    return values


def _release_group_preferences(local_group: str = "", preferred_subbers: list[str] | None = None) -> list[str]:
    groups: list[str] = []
    seen: set[str] = set()
    for value in [local_group, *(preferred_subbers or [])]:
        group = str(value or "").strip()
        key = group.casefold()
        if not group or group in {"Unknown", "Manual"} or key in seen:
            continue
        groups.append(group)
        seen.add(key)
    return groups


def _initial_search_queries(search_title: str, preferred_groups: list[str]) -> list[str]:
    queries = []
    for group in preferred_groups:
        queries.append(f"{group} {search_title}")
        queries.append(f"{search_title} {group}")
    queries.append(search_title)
    return _unique_queries(queries)


def _unique_queries(queries: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = str(query or "").strip()
        key = normalized.casefold()
        if normalized and key not in seen:
            unique.append(normalized)
            seen.add(key)
    return unique


def search_nyaa_rss(query: str) -> list[dict[str, Any]]:
    cache_key = query.strip().casefold()
    now = time.time()
    if NYAA_RSS_CACHE_TTL_SECONDS > 0 and NYAA_RSS_CACHE_MAX_ENTRIES != 0:
        with _RSS_CACHE_LOCK:
            cached = _RSS_CACHE.get(cache_key)
            if cached is not None and now - cached[0] < NYAA_RSS_CACHE_TTL_SECONDS:
                return [dict(release) for release in cached[1]]
            if cached is not None:
                _RSS_CACHE.pop(cache_key, None)

    releases = _fetch_nyaa_rss(query)
    if NYAA_RSS_CACHE_TTL_SECONDS > 0 and NYAA_RSS_CACHE_MAX_ENTRIES != 0:
        with _RSS_CACHE_LOCK:
            _prune_rss_cache_locked(now)
            _RSS_CACHE[cache_key] = (now, [dict(release) for release in releases])
            _prune_rss_cache_locked(now)
    return [dict(release) for release in releases]


def _prune_rss_cache_locked(now: float | None = None) -> None:
    if NYAA_RSS_CACHE_MAX_ENTRIES == 0:
        _RSS_CACHE.clear()
        return
    current = time.time() if now is None else now
    if NYAA_RSS_CACHE_TTL_SECONDS > 0:
        expired_keys = [key for key, (stored_at, _releases) in _RSS_CACHE.items() if current - stored_at >= NYAA_RSS_CACHE_TTL_SECONDS]
        for key in expired_keys:
            _RSS_CACHE.pop(key, None)
    if NYAA_RSS_CACHE_MAX_ENTRIES <= 0:
        return
    while len(_RSS_CACHE) > NYAA_RSS_CACHE_MAX_ENTRIES:
        oldest_key = min(_RSS_CACHE, key=lambda key: _RSS_CACHE[key][0])
        _RSS_CACHE.pop(oldest_key, None)


def _fetch_nyaa_rss(query: str) -> list[dict[str, Any]]:
    params = {
        "page": "rss",
        "q": query,
        "c": "1_2",
        "f": "0",
    }
    url = f"{NYAA_RSS_URL}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "User-Agent": "nyaarr/0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            root = ET.fromstring(response.read())
    except (OSError, ET.ParseError) as exc:
        raise TorrentFinderError(f"Nyaa RSS search failed: {exc}.") from exc

    releases = []
    for item in root.findall("./channel/item"):
        title = _child_text(item, "title")
        link = _child_text(item, "link")
        if not title or not link:
            continue

        guid = _child_text(item, "guid")
        nyaa_id = _torrent_id(link) or _torrent_id(guid)
        releases.append(
            {
                "title": title,
                "detail_url": guid if "/view/" in guid else (f"https://nyaa.si/view/{nyaa_id}" if nyaa_id else link),
                "torrent_url": f"https://nyaa.si/download/{nyaa_id}.torrent" if nyaa_id else "",
                "guid": guid,
                "published": _child_text(item, "pubDate"),
                "seeders": _int_child(item, f"{NYAA_NAMESPACE}seeders"),
                "leechers": _int_child(item, f"{NYAA_NAMESPACE}leechers"),
                "downloads": _int_child(item, f"{NYAA_NAMESPACE}downloads"),
                "infohash": _child_text(item, f"{NYAA_NAMESPACE}infoHash"),
                "category": _child_text(item, f"{NYAA_NAMESPACE}category"),
                "category_id": _child_text(item, f"{NYAA_NAMESPACE}categoryId"),
                "size": _child_text(item, f"{NYAA_NAMESPACE}size"),
                "size_bytes": _size_bytes(_child_text(item, f"{NYAA_NAMESPACE}size")),
                "trusted": _child_text(item, f"{NYAA_NAMESPACE}trusted"),
                "remake": _child_text(item, f"{NYAA_NAMESPACE}remake"),
                "release_group": _release_group(title),
                "release_kind": _release_kind(title),
                "episode": _episode_number(title),
                "source_kind": _source_kind(title),
                "resolution": _resolution(title),
            }
        )

    return releases

def _search_nyaa_rss_queries(queries: list[str]) -> list[tuple[str, list[dict[str, Any]], str]]:
    unique_queries: list[str] = []
    seen: set[str] = set()
    for query in queries:
        normalized = query.strip()
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        unique_queries.append(normalized)

    if not unique_queries:
        return []

    if NYAA_RSS_SEARCH_WORKERS <= 1 or len(unique_queries) == 1:
        results = []
        for query in unique_queries:
            try:
                results.append((query, search_nyaa_rss(query), ""))
            except TorrentFinderError as exc:
                results.append((query, [], str(exc)))
        return results

    results_by_query: dict[str, tuple[list[dict[str, Any]], str]] = {}
    workers = min(NYAA_RSS_SEARCH_WORKERS, len(unique_queries))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers, thread_name_prefix="nyaa-rss") as executor:
        futures = {executor.submit(search_nyaa_rss, query): query for query in unique_queries}
        for future in concurrent.futures.as_completed(futures):
            query = futures[future]
            try:
                results_by_query[query] = (future.result(), "")
            except TorrentFinderError as exc:
                results_by_query[query] = ([], str(exc))

    return [(query, *results_by_query.get(query, ([], ""))) for query in unique_queries]

def _load_episode_search_releases(
    search_title: str,
    season_number: int,
    related_releases: list[dict[str, Any]],
    missing_episodes: set[int],
    notices: list[str],
    preferred_groups: list[str] | None = None,
) -> list[dict[str, Any]]:
    loaded_releases = list(related_releases)
    loaded_keys = {_release_identity(release) for release in loaded_releases}
    episode_by_query: dict[str, int] = {}
    for episode in sorted(missing_episodes):
        queries = [f"{search_title} {episode:02d}"]
        for group in preferred_groups or []:
            queries.insert(0, f"{search_title} {group} {episode:02d}")
            queries.insert(0, f"{group} {search_title} {episode:02d}")
        for query in _unique_queries(queries):
            if NYAA_MAX_EPISODE_SEARCH_QUERIES and len(episode_by_query) >= NYAA_MAX_EPISODE_SEARCH_QUERIES:
                notices.append(f"Episode RSS fan-out was capped at {NYAA_MAX_EPISODE_SEARCH_QUERIES} query/queries for this refresh.")
                break
            episode_by_query[query] = episode
        if NYAA_MAX_EPISODE_SEARCH_QUERIES and len(episode_by_query) >= NYAA_MAX_EPISODE_SEARCH_QUERIES:
            break
    for query, episode_releases, error in _search_nyaa_rss_queries(list(episode_by_query)):
        episode = episode_by_query[query]
        if error:
            notices.append(f"Episode {episode:02d} RSS search failed: {error}")
            continue
        for release in episode_releases:
            if (
                release.get("episode") != episode
                or not _title_matches(search_title, release["title"])
                or not _season_matches(season_number, release["title"])
            ):
                continue
            key = _release_identity(release)
            if key in loaded_keys:
                continue
            loaded_keys.add(key)
            loaded_releases.append(release)
    return loaded_releases



def _should_try_large_backlog_batch_search(
    anime: dict[str, Any],
    releases: list[dict[str, Any]],
    missing_episodes: set[int],
) -> bool:
    if len(missing_episodes) < LARGE_BACKLOG_BATCH_SEARCH_THRESHOLD:
        return False
    return not _has_compatible_batch_candidate(anime, releases)


def _has_compatible_batch_candidate(anime: dict[str, Any], releases: list[dict[str, Any]]) -> bool:
    batch_releases = [release for release in releases if release.get("release_kind") == "batch"]
    if not batch_releases:
        return False
    local_group = _local_release_group_preference(anime)
    if _local_episode_count(anime) <= 0 or not local_group:
        return True
    return any(str(release.get("release_group") or "").casefold() == local_group.casefold() for release in batch_releases)

def _should_load_batch_fallback_searches(
    anime: dict[str, Any],
    releases: list[dict[str, Any]],
    missing_episodes: set[int],
) -> bool:
    if not missing_episodes or not _local_release_group_preference(anime):
        return False
    episode_releases = [release for release in releases if release.get("release_kind") == "episode"]
    return bool(_batch_fallback_episode_numbers(anime, episode_releases, missing_episodes))


def _load_batch_search_releases(
    search_title: str,
    season_number: int,
    related_releases: list[dict[str, Any]],
    preferred_group: str,
    notices: list[str],
) -> list[dict[str, Any]]:
    queries = [f"{search_title} batch", f"{search_title} complete"]
    if preferred_group:
        queries.extend([f"{preferred_group} {search_title}", f"{search_title} {preferred_group}"])

    loaded_releases = list(related_releases)
    loaded_keys = {_release_identity(release) for release in loaded_releases}
    for query, batch_releases, error in _search_nyaa_rss_queries(queries):
        if error:
            notices.append(f"Batch fallback RSS search failed for {query}: {error}")
            continue
        for release in batch_releases:
            if (
                release.get("release_kind") != "batch"
                or not _title_matches(search_title, release["title"])
                or not _season_matches(season_number, release["title"])
            ):
                continue
            key = _release_identity(release)
            if key in loaded_keys:
                continue
            loaded_keys.add(key)
            loaded_releases.append(release)
    return loaded_releases


def _select_candidates(
    releases: list[dict[str, Any]],
    anime: dict[str, Any] | None = None,
    preferred_groups: list[str] | None = None,
) -> list[dict[str, Any]]:
    anime = anime or {}
    local_episode_count = _local_episode_count(anime)
    local_release_group = _local_release_group_preference(anime)
    group_preferences = _release_group_preferences(local_release_group, preferred_groups)
    missing_episodes = _missing_episodes(anime)
    quality_preference = _quality_preference(anime)
    useful_releases = _preferred_quality_releases([
        release
        for release in releases
        if release["release_kind"] in {"batch", "episode"}
        and _quality_allows_release(release, quality_preference)
    ], quality_preference)
    if not useful_releases:
        return []

    batch_releases = [release for release in useful_releases if release["release_kind"] == "batch"]
    if local_episode_count == 0 and batch_releases:
        preferred_group = _preferred_group(batch_releases, group_preferences)
        return _sort_releases(
            [release for release in batch_releases if release["release_group"] == preferred_group]
            or batch_releases
        )[:5]

    episode_releases = [
        release
        for release in useful_releases
        if release["release_kind"] == "episode"
        and (not missing_episodes or release.get("episode") in missing_episodes)
    ]
    if episode_releases:
        same_group = _episode_releases_from_consistent_group(episode_releases, missing_episodes, group_preferences)
        fallback_batches = _same_subber_batch_fallback_releases(
            batch_releases,
            same_group,
            missing_episodes,
            anime,
            local_release_group,
        )
        if fallback_batches:
            return fallback_batches
        if same_group:
            return _best_release_per_episode(same_group)[:24]

    if batch_releases:
        preferred_group = _preferred_group(batch_releases, group_preferences)
        return _sort_releases(
            [release for release in batch_releases if release["release_group"] == preferred_group]
            or batch_releases
        )[:5]

    return []


def _episode_releases_from_consistent_group(
    episode_releases: list[dict[str, Any]],
    missing_episodes: set[int],
    preferred_groups: list[str] | None = None,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for release in episode_releases:
        groups.setdefault(str(release.get("release_group") or "Unknown"), []).append(release)

    ranked_groups = []
    for group, releases in groups.items():
        covered = {
            int(release["episode"])
            for release in releases
            if isinstance(release.get("episode"), int)
        }
        covered_missing = covered & missing_episodes if missing_episodes else covered
        if missing_episodes and not covered_missing:
            continue
        ranked_groups.append(
            (
                _group_preference_rank(group, preferred_groups),
                missing_episodes.issubset(covered) if missing_episodes else True,
                len(covered_missing),
                len(covered),
                sum(int(release.get("seeders") or 0) for release in releases),
                group,
                releases,
            )
        )
    if not ranked_groups:
        return []

    ranked_groups.sort(reverse=True, key=lambda item: item[:6])
    return _sort_episode_releases(ranked_groups[0][6])


def _same_subber_batch_fallback_releases(
    batch_releases: list[dict[str, Any]],
    episode_releases: list[dict[str, Any]],
    missing_episodes: set[int],
    anime: dict[str, Any],
    local_release_group: str,
) -> list[dict[str, Any]]:
    if not batch_releases or not local_release_group:
        return []
    fallback_episodes = _batch_fallback_episode_numbers(anime, episode_releases, missing_episodes)
    if not fallback_episodes:
        return []
    same_group_batches = [
        release
        for release in batch_releases
        if str(release.get("release_group") or "").casefold() == local_release_group.casefold()
    ]
    if not same_group_batches:
        return []

    selected = []
    for release in _sort_releases(same_group_batches)[:5]:
        candidate = dict(release)
        candidate["fallback_reason"] = "same-subber batch fallback for stalled or low-seed episodes"
        candidate["batch_fallback_episodes"] = sorted(fallback_episodes)
        selected.append(candidate)
    return selected


def _batch_fallback_episode_numbers(
    anime: dict[str, Any],
    episode_releases: list[dict[str, Any]],
    missing_episodes: set[int],
) -> set[int]:
    if not missing_episodes:
        return set()
    preferred_group = _local_release_group_preference(anime)
    if not preferred_group:
        return set()
    fallback_episodes = _stale_stalled_episode_numbers(anime) & missing_episodes
    fallback_episodes.update(
        _low_seed_missing_episode_numbers(episode_releases, missing_episodes, preferred_group)
    )
    return fallback_episodes


def _low_seed_missing_episode_numbers(
    episode_releases: list[dict[str, Any]],
    missing_episodes: set[int],
    preferred_group: str,
) -> set[int]:
    if LOW_SEED_BATCH_FALLBACK_SEEDERS <= 0:
        return set()
    best_seeders = {episode: 0 for episode in missing_episodes}
    for release in episode_releases:
        if str(release.get("release_group") or "").casefold() != preferred_group.casefold():
            continue
        episode = release.get("episode")
        if not isinstance(episode, int) or episode not in missing_episodes:
            continue
        best_seeders[episode] = max(best_seeders.get(episode, 0), _release_seeders(release))
    return {episode for episode, seeders in best_seeders.items() if seeders < LOW_SEED_BATCH_FALLBACK_SEEDERS}


def _stale_stalled_episode_numbers(anime: dict[str, Any]) -> set[int]:
    queues = anime.get("download_queues")
    if not isinstance(queues, list):
        queue = anime.get("download_queue")
        queues = [queue] if isinstance(queue, dict) else []
    now = datetime.now(timezone.utc)
    episodes: set[int] = set()
    for queue in queues:
        if not isinstance(queue, dict) or str(queue.get("status") or "").casefold() != "stalled":
            continue
        progress = _float_value(queue.get("progress"))
        if progress is not None and progress >= 1:
            continue
        queued_at = _parse_datetime(queue.get("queued_at") or queue.get("updated_at"))
        if queued_at is not None and (now - queued_at).total_seconds() < STALLED_TORRENT_BATCH_FALLBACK_SECONDS:
            continue
        episode = _queue_episode_number(queue)
        if episode is not None:
            episodes.add(episode)
    return episodes


def _queue_episode_number(queue: dict[str, Any]) -> int | None:
    episode = _positive_int(queue.get("episode"))
    if episode is not None:
        return episode
    wanted = queue.get("wanted_episodes")
    if isinstance(wanted, list) and len(wanted) == 1:
        return _positive_int(wanted[0])
    return None


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _release_seeders(release: dict[str, Any]) -> int:
    try:
        return int(release.get("seeders") or 0)
    except (TypeError, ValueError):
        return 0


def _float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _preferred_group(releases: list[dict[str, Any]], preferred_groups: list[str] | None = None) -> str:
    groups = [release["release_group"] for release in releases if release.get("release_group")]
    if not groups:
        return "Unknown"
    for preferred_group in preferred_groups or []:
        if any(group.casefold() == preferred_group.casefold() for group in groups):
            return preferred_group
    counts = Counter(groups)
    return counts.most_common(1)[0][0]


def _group_preference_rank(group: str, preferred_groups: list[str] | None = None) -> int:
    for index, preferred_group in enumerate(preferred_groups or []):
        if group.casefold() == preferred_group.casefold():
            return 1000 - index
    return 0

def _local_release_group_preference(anime: dict[str, Any]) -> str:
    groups = []
    episode_files = anime.get("episode_files")
    if isinstance(episode_files, list):
        for episode_file in episode_files:
            group = _release_group(Path(str(episode_file or "")).name)
            if group and group != "Unknown":
                groups.append(group)
    if groups:
        return Counter(groups).most_common(1)[0][0]

    queues = anime.get("download_queues")
    if not isinstance(queues, list):
        queue = anime.get("download_queue")
        queues = [queue] if isinstance(queue, dict) else []
    for queue in queues:
        if not isinstance(queue, dict):
            continue
        if queue.get("status") not in {"queued", "downloading", "paused", "stalled", "pending_safety", "completed", "imported"}:
            continue
        group = str(queue.get("release_group") or "").strip() or _release_group(str(queue.get("title") or ""))
        if group and group not in {"Unknown", "Manual"}:
            groups.append(group)
    return Counter(groups).most_common(1)[0][0] if groups else ""


def _selection_strategy(candidates: list[dict[str, Any]]) -> str:
    if not candidates:
        return "No batch or per-episode candidates found"
    quality = _quality_label(candidates[0])
    if candidates[0]["release_kind"] == "batch":
        if candidates[0].get("fallback_reason"):
            return f"Preferred {quality} same-subber batch fallback from {candidates[0]['release_group']}"
        return f"Preferred {quality} batch releases from {candidates[0]['release_group']}"
    return f"Preferred {quality} per-episode releases from {candidates[0]['release_group']}"


def _sort_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        releases,
        key=lambda release: (
            release.get("seeders", 0),
            release.get("downloads", 0),
            -(release.get("size_bytes") or 0),
        ),
        reverse=True,
    )


def _sort_episode_releases(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        releases,
        key=lambda release: (
            release.get("episode") or 0,
            release.get("seeders", 0),
            release.get("downloads", 0),
        ),
    )


def _best_release_per_episode(releases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    best_by_episode: dict[int, dict[str, Any]] = {}
    for release in releases:
        episode = release.get("episode")
        if not isinstance(episode, int):
            continue
        existing = best_by_episode.get(episode)
        if existing is None or (
            int(release.get("seeders") or 0),
            int(release.get("downloads") or 0),
        ) > (
            int(existing.get("seeders") or 0),
            int(existing.get("downloads") or 0),
        ):
            best_by_episode[episode] = release
    return [best_by_episode[episode] for episode in sorted(best_by_episode)]


def _title_matches(search_title: str, torrent_title: str) -> bool:
    search_tokens = _title_tokens(search_title)
    torrent_tokens = _torrent_series_tokens(torrent_title)
    if not search_tokens:
        return False
    if len(search_tokens) == 1:
        return torrent_tokens == search_tokens
    return torrent_tokens[: len(search_tokens)] == search_tokens


def _title_tokens(value: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", value.casefold())
        if token not in {"the", "a", "an", "season", "s"} and not re.fullmatch(r"(?:19|20)\d{2}", token)
    ]


def _torrent_series_tokens(title: str) -> list[str]:
    value = _remove_leading_release_group(title)
    value = re.sub(r"\.(?:mkv|mp4|avi|m2ts|mov|webm)\s*$", "", value.strip(), flags=re.IGNORECASE)
    value = re.split(
        r"\bS\d{1,2}E\d{1,3}(?=\b|v\d|\.|$)|\bS\d{1,2}\s*-\s*\d{1,3}(?=\s|v\d|\[|\(|\.|$)|(?:^|\s)-\s*\d{1,3}(?=\s|v\d|\[|\(|\.|$)|\bEP?\s*\d{1,3}\b|\b\d{1,3}\s*[-~]\s*\d{1,3}\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    value = re.split(
        r"\b(?:batch|complete|1080p|720p|2160p|480p|web[-\s]?dl|webrip|blu[-\s]?ray|bdrip|bdmv|remux|x26[45]|h\.?\s*26[45]|hevc|av1)\b",
        value,
        maxsplit=1,
        flags=re.IGNORECASE,
    )[0]
    return _title_tokens(value)


def _remove_leading_release_group(value: str) -> str:
    return re.sub(r"^\s*\[[^\]]+\]\s*", "", value)


def _selected_season_number(anime: dict[str, Any]) -> int:
    try:
        season_number = int(anime.get("season_number", 1))
    except (TypeError, ValueError):
        return 1
    return max(season_number, 1)


def _season_matches(selected_season: int, torrent_title: str) -> bool:
    torrent_season = _torrent_season_number(torrent_title)
    if selected_season == 1:
        return torrent_season in {None, 1}
    return torrent_season == selected_season


def _torrent_season_number(title: str) -> int | None:
    normalized = title.casefold()
    patterns = [
        r"\bS(\d{1,2})(?:E\d{1,3})?\b",
        r"\bseason\s*(\d{1,2})\b",
        r"\b(\d{1,2})(?:st|nd|rd|th)\s+season\b",
        r"\bs\s*(\d{1,2})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    if re.search(r"\b(?:ii|2nd)\b", normalized):
        return 2
    if re.search(r"\b(?:iii|3rd)\b", normalized):
        return 3
    return None


def _release_group(title: str) -> str:
    match = re.match(r"^\[([^\]]+)\]", title)
    if match:
        return match.group(1).strip()

    normalized = _release_title_without_suffix_notes(title)
    scene_match = re.search(
        r"(?:x26[45]|h\.?\s*26[45]|hevc|av1|web[-\s]?dl|webrip|bdrip|hdtv)[^-]{0,100}-([A-Za-z0-9][A-Za-z0-9._+]{1,31})$",
        normalized,
        flags=re.IGNORECASE,
    )
    if scene_match:
        group = scene_match.group(1).strip(" ._-")
        if group and group.casefold() not in {"dl", "rip", "sub", "subs", "multi", "dual", "audio"}:
            return group
    return "Unknown"


def _release_title_without_suffix_notes(title: str) -> str:
    value = re.sub(r"\.(?:mkv|mp4|avi|m2ts|mov|webm)\s*$", "", title.strip(), flags=re.IGNORECASE)
    while True:
        stripped = re.sub(r"\s+(?:\[[^\]]+\]|\([^)]*\))\s*$", "", value).strip()
        if stripped == value:
            return value
        value = stripped


def _release_kind(title: str) -> str:
    normalized = title.casefold()
    if _episode_number(title) is not None:
        return "episode"
    if any(word in normalized for word in ("batch", "complete")):
        return "batch"
    if re.search(r"\b(?:season|s)\s*\d{1,2}\b", normalized) or re.search(r"\b\d{1,3}\s*-\s*\d{1,3}\b", normalized):
        return "batch"
    return "unknown"


def _episode_number(title: str) -> int | None:
    patterns = [
        r"\bS\d{1,2}E(\d{1,3})(?=\b|v\d|\.|$)",
        r"\bS\d{1,2}\s*-\s*(\d{1,3})(?=\s|v\d|\[|\(|\.|$)",
        r"(?:^|\s)-\s*(\d{1,3})(?=\s|v\d|\[|\(|\.|$)",
        r"\bEP?\s*(\d{1,3})\b",
        r"(?:^|[\\/])\D{0,30}(\d{1,3})(?=\s|v\d|\[|\(|\.|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, title, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _torrent_id(link: str) -> str | None:
    match = re.search(r"/(?:view|download)/(\d+)", link)
    return match.group(1) if match else None


def _source_kind(title: str) -> str:
    normalized = title.casefold()
    if re.search(r"\b(?:blu[-\s]?ray|bdrip|bdmv|bd|remux)\b", normalized):
        return "bluray"
    if re.search(r"\bweb(?:[-\s]?(?:dl|rip))?\b", normalized):
        return "web"
    return "unknown"


def _resolution(title: str) -> int | None:
    match = re.search(r"\b(2160|1440|1080|720|576|540|480)p\b", title, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _quality_preference(anime: dict[str, Any]) -> str:
    value = str(anime.get("quality_resolution") or anime.get("quality_profile") or "1080p").strip().casefold()
    if "bd" in value or "blu" in value:
        return "bd"
    if "720" in value:
        return "720p"
    return "1080p"


def _quality_allows_release(release: dict[str, Any], quality_preference: str) -> bool:
    if release.get("source_kind") == "bluray" and quality_preference != "bd":
        return False
    resolution = release.get("resolution")
    if not isinstance(resolution, int):
        return True
    if quality_preference == "720p":
        return resolution <= 720
    if quality_preference == "1080p":
        return resolution <= 1080
    return True


def _preferred_quality_releases(releases: list[dict[str, Any]], quality_preference: str) -> list[dict[str, Any]]:
    if not releases:
        return []
    if quality_preference == "bd":
        bluray_releases = [release for release in releases if release.get("source_kind") == "bluray"]
        return bluray_releases or releases

    preferred_resolution = 720 if quality_preference == "720p" else 1080
    for resolution in _resolution_fallbacks(preferred_resolution):
        matching = [release for release in releases if release.get("resolution") == resolution]
        if matching:
            return matching
    unknown_resolution = [release for release in releases if release.get("resolution") is None]
    return unknown_resolution or releases


def _resolution_fallbacks(preferred_resolution: int) -> list[int]:
    known = [2160, 1440, 1080, 720, 576, 540, 480]
    return [resolution for resolution in known if resolution <= preferred_resolution]


def _quality_label(release: dict[str, Any]) -> str:
    if release.get("source_kind") == "bluray":
        return "BD"
    resolution = release.get("resolution")
    return f"{resolution}p" if isinstance(resolution, int) else "unstated-resolution"


def _missing_episodes(anime: dict[str, Any]) -> set[int]:
    completion = anime.get("completion")
    if not isinstance(completion, dict):
        return set()
    target = _positive_int(completion.get("progress_target")) or _positive_int(completion.get("expected_episodes"))
    local_count = _positive_int(completion.get("local_episodes")) or 0
    if anime.get("library_state") == "Completed" or (target is not None and local_count >= target):
        return set()
    airing_episode = _positive_int(anime.get("airing_episode"))
    if airing_episode is not None:
        aired_target = max(airing_episode - 1, 0)
        target = min(target, aired_target) if target else aired_target
    if not target:
        return set()
    local_episode_numbers = _local_episode_numbers(anime)
    if local_episode_numbers:
        return {episode for episode in range(1, target + 1) if episode not in local_episode_numbers}
    return set(range(local_count + 1, target + 1))


def _local_episode_numbers(anime: dict[str, Any]) -> set[int]:
    episode_files = anime.get("episode_files")
    if not isinstance(episode_files, list):
        return set()
    episode_numbers: set[int] = set()
    for episode_file in episode_files:
        episode = _episode_number(Path(str(episode_file or "")).name)
        if episode is not None and episode > 0:
            episode_numbers.add(episode)
    return episode_numbers


def _local_episode_count(anime: dict[str, Any]) -> int:
    completion = anime.get("completion")
    if isinstance(completion, dict):
        value = _positive_int(completion.get("local_episodes"))
        if value is not None:
            return value
    episode_files = anime.get("episode_files")
    if isinstance(episode_files, list):
        return len(episode_files)
    return 0


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(str(value or "").strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _size_bytes(value: str) -> int:
    match = re.search(r"([\d.]+)\s*([KMGT]i?B)", value, flags=re.IGNORECASE)
    if not match:
        return 0
    amount = float(match.group(1))
    units = {
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    return int(amount * units.get(match.group(2).casefold(), 1))


def _release_identity(release: dict[str, Any]) -> str:
    for key in ("infohash", "detail_url", "torrent_url", "guid", "title"):
        value = str(release.get(key) or "").strip()
        if value:
            return f"{key}:{value.casefold()}"
    return ""


def _child_text(item: ET.Element, tag: str) -> str:
    child = item.find(tag)
    return child.text.strip() if child is not None and child.text else ""


def _int_child(item: ET.Element, tag: str) -> int:
    value = _child_text(item, tag)
    try:
        return int(value)
    except ValueError:
        return 0
