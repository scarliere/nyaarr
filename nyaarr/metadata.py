from __future__ import annotations

import json
import copy
import concurrent.futures
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timezone
from html import unescape
from pathlib import Path
from time import time
from typing import Any

from .anilist_client import AniListClientError, AniListRateLimitError, client as anilist_client
from .metrics import timed
from .models import AniListSnapshot, EpisodeAiringRecord


ANILIST_URL = "https://graphql.anilist.co"
ANIME_OFFLINE_DATABASE_RELEASE_URL = "https://api.github.com/repos/manami-project/anime-offline-database/releases/latest"
KITSU_SEARCH_ANIME_URL = "https://kitsu.app/api/edge/anime"
TMDB_SEARCH_TV_URL = "https://api.themoviedb.org/3/search/tv"
TMDB_IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w342"
HTTP_TIMEOUT_SECONDS = 10
OFFLINE_CACHE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
OFFLINE_CACHE_DIR = Path("data/cache")
OFFLINE_CACHE_FILE = OFFLINE_CACHE_DIR / "anime-offline-database-minified.json"
OFFLINE_CACHE_METADATA_FILE = OFFLINE_CACHE_DIR / "anime-offline-database-cache.json"
OFFLINE_DATABASE_PATHS = (
    OFFLINE_CACHE_FILE,
    Path("data/anime-offline-database-minified.json"),
    Path("data/anime-offline-database.json"),
)

_offline_database_cache: dict[str, Any] | None = None
_offline_database_cache_path: Path | None = None
_offline_database_cache_mtime: float | None = None
_SEARCH_CACHE_TTL_SECONDS = 5 * 60
_SEARCH_CACHE: dict[str, tuple[float, tuple[list[dict[str, Any]], list[str]]]] = {}
_SEARCH_INFLIGHT: dict[str, concurrent.futures.Future[tuple[list[dict[str, Any]], list[str]]]] = {}
_SEARCH_LOCK = threading.RLock()


class MetadataProviderError(RuntimeError):
    pass


class MetadataRateLimitError(MetadataProviderError):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = max(int(retry_after), 1)


def search_anime_metadata(query: str) -> tuple[list[dict[str, Any]], list[str]]:
    cache_key = query.strip().casefold()
    now = time()
    with _SEARCH_LOCK:
        cached = _SEARCH_CACHE.get(cache_key)
        if cached is not None and now - cached[0] < _SEARCH_CACHE_TTL_SECONDS:
            return copy.deepcopy(cached[1])
        future = _SEARCH_INFLIGHT.get(cache_key)
        owns_request = future is None
        if future is None:
            future = concurrent.futures.Future()
            _SEARCH_INFLIGHT[cache_key] = future
    if owns_request:
        try:
            with timed('provider.metadata_search'):
                result = _search_anime_metadata_uncached(query)
            with _SEARCH_LOCK:
                _SEARCH_CACHE[cache_key] = (now, copy.deepcopy(result))
            future.set_result(result)
        except Exception as exc:
            future.set_exception(exc)
        finally:
            with _SEARCH_LOCK:
                _SEARCH_INFLIGHT.pop(cache_key, None)
    return copy.deepcopy(future.result(timeout=HTTP_TIMEOUT_SECONDS * 4 + 2))


def _search_anime_metadata_uncached(query: str) -> tuple[list[dict[str, Any]], list[str]]:
    if not query:
        return [], []

    notices: list[str] = []
    merged_results: list[dict[str, Any]] = []

    try:
        results = search_anilist(query)
        if results:
            merged_results.extend(results)
            if _metadata_results_have_poster(results):
                return _enrich_missing_metadata_posters(merged_results), notices
            notices.append("AniList returned metadata without posters; checking fallback providers for artwork.")
    except MetadataProviderError as exc:
        notices.append(str(exc))

    try:
        results = search_anime_offline_database(query)
        if results:
            merged_results.extend(_new_metadata_results(merged_results, results))
            if not notices:
                notices.append("AniList returned no usable results; showing anime-offline-database results.")
            if _metadata_results_have_poster(results):
                return _enrich_missing_metadata_posters(merged_results), notices
    except MetadataProviderError as exc:
        notices.append(str(exc))

    try:
        results = search_kitsu(query)
        if results:
            merged_results.extend(_new_metadata_results(merged_results, results))
            if _metadata_results_have_poster(results):
                return _enrich_missing_metadata_posters(merged_results), notices
            if not merged_results:
                notices.append("AniList and anime-offline-database returned no usable results; showing Kitsu results.")
    except MetadataProviderError as exc:
        notices.append(str(exc))

    try:
        results = search_tmdb(query)
        if results:
            merged_results.extend(_new_metadata_results(merged_results, results))
            if not merged_results:
                notices.append("AniList, anime-offline-database, and Kitsu returned no usable results; showing TMDB results.")
            return _enrich_missing_metadata_posters(merged_results), notices
    except MetadataProviderError as exc:
        notices.append(str(exc))

    if merged_results:
        return _enrich_missing_metadata_posters(merged_results), notices
    return [], notices





def _enrich_missing_metadata_posters(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_results: list[dict[str, Any]] = []
    for result in results:
        if not isinstance(result, dict):
            continue
        enriched = dict(result)
        if not str(enriched.get("poster") or "").strip():
            poster_match = _poster_match_for_metadata_result(enriched, results)
            if poster_match is not None:
                enriched["poster"] = str(poster_match.get("poster") or "")
                enriched["poster_source"] = str(poster_match.get("source") or "Unknown")
        enriched_results.append(enriched)
    return enriched_results


def _poster_match_for_metadata_result(target: dict[str, Any], results: list[dict[str, Any]]) -> dict[str, Any] | None:
    target_title = _metadata_compare_text(target.get("title") or target.get("original_title"))
    target_original = _metadata_compare_text(target.get("original_title") or target.get("title"))
    target_year = str(target.get("year") or "").strip()
    for candidate in results:
        if not isinstance(candidate, dict) or candidate is target:
            continue
        if not str(candidate.get("poster") or "").strip():
            continue
        candidate_title = _metadata_compare_text(candidate.get("title") or candidate.get("original_title"))
        candidate_original = _metadata_compare_text(candidate.get("original_title") or candidate.get("title"))
        candidate_year = str(candidate.get("year") or "").strip()
        titles_match = target_title and target_title in {candidate_title, candidate_original}
        originals_match = target_original and target_original in {candidate_title, candidate_original}
        years_match = not target_year or not candidate_year or target_year == "Unknown" or candidate_year == "Unknown" or target_year == candidate_year
        if years_match and (titles_match or originals_match):
            return candidate
    return None


def _metadata_compare_text(value: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", str(value or "").casefold()))

def _metadata_results_have_poster(results: list[dict[str, Any]]) -> bool:
    return any(str(result.get("poster") or "").strip() for result in results if isinstance(result, dict))


def _metadata_dedupe_key(result: dict[str, Any]) -> str:
    provider_ids = result.get("provider_ids")
    if isinstance(provider_ids, dict):
        for provider in ("anilist", "mal", "kitsu", "tmdb"):
            value = provider_ids.get(provider)
            if value:
                return f"{provider}:{value}"
    return f"{result.get('source', '')}:{result.get('title', '')}:{result.get('year', '')}".casefold()


def _new_metadata_results(existing: list[dict[str, Any]], incoming: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {_metadata_dedupe_key(result) for result in existing if isinstance(result, dict)}
    new_results = []
    for result in incoming:
        if not isinstance(result, dict):
            continue
        key = _metadata_dedupe_key(result)
        if key in seen:
            continue
        seen.add(key)
        new_results.append(result)
    return new_results

ANILIST_MEDIA_FIELDS = """
  id
  idMal
  title {
    romaji
    english
    native
  }
  synonyms
  description(asHtml: false)
  seasonYear
  season
  format
  status
  startDate {
    year
    month
    day
  }
  endDate {
    year
    month
    day
  }
  countryOfOrigin
  source(version: 3)
  isAdult
  updatedAt
  episodes
  duration
  averageScore
  nextAiringEpisode {
    airingAt
    episode
    timeUntilAiring
  }
  genres
  coverImage {
    large
  }
  studios(isMain: true) {
    nodes {
      name
    }
  }
"""


def search_anilist(query: str) -> list[dict[str, Any]]:
    graphql = f"""
    query ($search: String) {{
      Page(page: 1, perPage: 10) {{
        media(search: $search, type: ANIME, sort: SEARCH_MATCH) {{
{ANILIST_MEDIA_FIELDS}
        }}
      }}
    }}
    """
    payload = {"query": graphql, "variables": {"search": query}}
    data = _post_json(ANILIST_URL, payload)

    if "errors" in data:
        raise MetadataProviderError("AniList returned an API error.")

    media = data.get("data", {}).get("Page", {}).get("media", [])
    return [_map_anilist_item(item, preferred_title=query) for item in media]


def search_anilist_by_id(anilist_id: Any) -> dict[str, Any] | None:
    try:
        media_id = int(str(anilist_id).strip())
    except (TypeError, ValueError):
        return None
    if media_id <= 0:
        return None

    snapshot = fetch_anilist_snapshot(media_id)
    return snapshot.get("media") if isinstance(snapshot, dict) else None


def fetch_anilist_snapshot(anilist_id: Any) -> AniListSnapshot | None:
    try:
        media_id = int(str(anilist_id).strip())
    except (TypeError, ValueError):
        return None
    if media_id <= 0:
        return None
    graphql = f"""
    query ($id: Int, $now: Int) {{
      Media(id: $id, type: ANIME) {{
{ANILIST_MEDIA_FIELDS}
      }}
      past: Page(page: 1, perPage: 25) {{
        airingSchedules(
          mediaId: $id, notYetAired: false,
          airingAt_lesser: $now, sort: TIME_DESC
        ) {{
          episode
          airingAt
          mediaId
        }}
      }}
      future: Page(page: 1, perPage: 25) {{
        airingSchedules(
          mediaId: $id, notYetAired: true,
          airingAt_greater: $now, sort: TIME
        ) {{
          episode
          airingAt
          mediaId
        }}
      }}
    }}
    """
    data = _post_json(
        ANILIST_URL,
        {"query": graphql, "variables": {"id": media_id, "now": int(time() // 300 * 300)}},
    )
    if "errors" in data:
        raise MetadataProviderError("AniList returned an API error.")
    payload = data.get("data", {})
    media = payload.get("Media")
    if not isinstance(media, dict):
        return None
    return {
        "media": _map_anilist_item(media),
        "past_airings": _map_anilist_airings(payload.get("past", {}).get("airingSchedules", [])),
        "future_airings": _map_anilist_airings(payload.get("future", {}).get("airingSchedules", [])),
    }


def fetch_anilist_airing_window(
    media_ids: list[Any],
    start_at: int,
    end_at: int,
    *,
    page: int = 1,
) -> tuple[list[EpisodeAiringRecord], bool]:
    selected = sorted({int(value) for value in media_ids if str(value or "").isdigit() and int(value) > 0})
    if not selected:
        return [], False
    graphql = """
    query ($ids: [Int], $start: Int, $end: Int, $page: Int) {
      Page(page: $page, perPage: 50) {
        pageInfo {
          hasNextPage
        }
        airingSchedules(
          mediaId_in: $ids,
          airingAt_greater: $start,
          airingAt_lesser: $end,
          sort: TIME
        ) {
          episode
          airingAt
          mediaId
        }
      }
    }
    """
    data = _post_json(
        ANILIST_URL,
        {
            "query": graphql,
            "variables": {
                "ids": selected,
                "start": int(start_at),
                "end": int(end_at),
                "page": max(int(page), 1),
            },
        },
    )
    if "errors" in data:
        raise MetadataProviderError("AniList returned an API error.")
    page_payload = data.get("data", {}).get("Page", {})
    records = _map_anilist_airings(page_payload.get("airingSchedules", []))
    has_next = bool(page_payload.get("pageInfo", {}).get("hasNextPage"))
    return records, has_next


def search_anime_offline_database(query: str) -> list[dict[str, Any]]:
    database_path = _offline_database_path()
    if database_path is None:
        raise MetadataProviderError(
            "anime-offline-database fallback is not available. Cache download failed, or set ANIME_OFFLINE_DATABASE_PATH."
        )

    try:
        database = _load_offline_database(database_path)
    except (OSError, json.JSONDecodeError) as exc:
        raise MetadataProviderError(f"anime-offline-database read failed: {exc}.") from exc

    normalized = query.casefold()
    results = []
    for item in database.get("data", []):
        searchable_values = [item.get("title", ""), *item.get("synonyms", [])]
        if any(normalized in value.casefold() for value in searchable_values if value):
            results.append(_map_offline_database_item(item))
        if len(results) >= 10:
            break

    return results


def search_kitsu(query: str) -> list[dict[str, Any]]:
    params = {
        "filter[text]": query,
        "page[limit]": "10",
    }
    url = f"{KITSU_SEARCH_ANIME_URL}?{urllib.parse.urlencode(params)}"
    data = _get_json(
        url,
        {
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/vnd.api+json",
        },
        "Kitsu request failed",
    )
    return [_map_kitsu_item(item) for item in data.get("data", [])]


def search_tmdb(query: str) -> list[dict[str, Any]]:
    bearer_token = os.environ.get("TMDB_BEARER_TOKEN", "").strip()
    api_key = os.environ.get("TMDB_API_KEY", "").strip()

    if not bearer_token and not api_key:
        raise MetadataProviderError("TMDB fallback is not configured. Set TMDB_BEARER_TOKEN or TMDB_API_KEY.")

    params = {
        "query": query,
        "include_adult": "false",
        "language": "en-US",
        "page": "1",
    }
    if api_key and not bearer_token:
        params["api_key"] = api_key

    url = f"{TMDB_SEARCH_TV_URL}?{urllib.parse.urlencode(params)}"
    headers = {}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    data = _get_json(url, headers)
    return [_map_tmdb_item(item) for item in data.get("results", [])[:10]]


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    if url == ANILIST_URL:
        try:
            return anilist_client.execute(
                str(payload.get("query") or ""),
                payload.get("variables") if isinstance(payload.get("variables"), dict) else {},
            )
        except AniListRateLimitError as exc:
            raise MetadataRateLimitError(str(exc), exc.retry_after) from exc
        except AniListClientError as exc:
            raise MetadataProviderError(str(exc)) from exc
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "nyaarr/0.1",
        },
        method="POST",
    )
    return _open_json(request, "AniList request failed")


def _get_json(url: str, headers: dict[str, str], error_prefix: str = "TMDB request failed") -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "nyaarr/0.1",
            **headers,
        },
        method="GET",
    )
    return _open_json(request, error_prefix)


def _open_json(request: urllib.request.Request, error_prefix: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise MetadataProviderError(f"{error_prefix}: HTTP {exc.code}.") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise MetadataProviderError(f"{error_prefix}: {exc}.") from exc


def _map_anilist_item(item: dict[str, Any], preferred_title: str = "") -> dict[str, Any]:
    title = item.get("title") or {}
    synonyms = item.get("synonyms", [])
    title_values = [
        title.get("english"),
        title.get("romaji"),
        title.get("native"),
        *synonyms,
    ]
    display_title = _anilist_display_title(title, synonyms, preferred_title)
    studios = item.get("studios", {}).get("nodes", [])
    studio = studios[0]["name"] if studios else "Unknown"
    year = item.get("seasonYear")
    score = item.get("averageScore")
    duration = item.get("duration")
    episodes = item.get("episodes")
    description = _clean_description(item.get("description") or "")
    airing = _anilist_airing_fields(item.get("nextAiringEpisode"))
    start_date = _anilist_fuzzy_date(item.get("startDate"))
    end_date = _anilist_fuzzy_date(item.get("endDate"))

    return {
        "title": display_title,
        "original_title": title.get("romaji") or title.get("native") or "Unknown",
        "year": str(year) if year else "Unknown",
        "status": _format_anilist_status(item.get("status")),
        "episodes": str(episodes) if episodes else "Unknown",
        "season_number": _infer_season_number(title_values),
        "runtime": f"{duration} min" if duration else "Unknown",
        "genres": item.get("genres") or [],
        "aliases": _unique_values(title_values),
        "provider_title": {
            "english": title.get("english") or "",
            "romaji": title.get("romaji") or "",
            "native": title.get("native") or "",
        },
        "studio": studio,
        "source": "AniList",
        "rating": f"{score}%" if score else "Unrated",
        "synopsis": description or "No synopsis available.",
        "poster": item.get("coverImage", {}).get("large") or "",
        "media_format": str(item.get("format") or "").replace("_", " ").title(),
        "release_season": str(item.get("season") or "").title(),
        "season_year": str(year) if year else "",
        "start_date": start_date,
        "end_date": end_date,
        "source_material": str(item.get("source") or "").replace("_", " ").title(),
        "country_of_origin": str(item.get("countryOfOrigin") or ""),
        "is_adult": bool(item.get("isAdult")),
        "anilist_updated_at": _unix_datetime(item.get("updatedAt")),
        "air_date": start_date or airing.get("air_date", ""),
        "next_airing_at": airing.get("next_airing_at", ""),
        "airing_episode": airing.get("airing_episode", ""),
        "airing_source": airing.get("airing_source", ""),
        "provider_ids": {
            "anilist": item.get("id"),
            "mal": item.get("idMal"),
        },
    }


def _map_anilist_airings(values: Any) -> list[EpisodeAiringRecord]:
    if not isinstance(values, list):
        return []
    records: list[EpisodeAiringRecord] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        episode = value.get("episode")
        airing_at = value.get("airingAt")
        media_id = value.get("mediaId")
        if not isinstance(episode, int) or episode <= 0 or not isinstance(airing_at, int) or airing_at <= 0:
            continue
        records.append(
            {
                "provider": "anilist",
                "media_id": str(media_id or ""),
                "episode": episode,
                "airing_at": datetime.fromtimestamp(airing_at, timezone.utc).isoformat().replace("+00:00", "Z"),
                "precision": "exact",
                "inference_source": "",
                "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        )
    return records


def _anilist_fuzzy_date(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    year = value.get("year")
    month = value.get("month")
    day = value.get("day")
    if not isinstance(year, int) or year <= 0:
        return ""
    if not isinstance(month, int) or not isinstance(day, int):
        return str(year)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return str(year)


def _unix_datetime(value: Any) -> str:
    if not isinstance(value, int) or value <= 0:
        return ""
    return datetime.fromtimestamp(value, timezone.utc).isoformat().replace("+00:00", "Z")

def _anilist_display_title(title: dict[str, Any], synonyms: list[Any], preferred_title: str = "") -> str:
    english = str(title.get("english") or "").strip()
    romaji = str(title.get("romaji") or "").strip()
    native = str(title.get("native") or "").strip()
    preferred = _matching_anilist_title(preferred_title, [english, romaji, native, *synonyms])
    if preferred:
        return preferred
    if english:
        english_cour = _cour_marker_number(english)
        if english_cour is not None and _part_marker_number(english) is None:
            for value in (romaji, *synonyms, native):
                candidate = str(value or "").strip()
                if candidate and _part_marker_number(candidate) == english_cour:
                    return candidate
        return english
    return romaji or native or "Unknown title"


def _matching_anilist_title(preferred_title: str, values: list[Any]) -> str:
    preferred_key = _metadata_compare_text(preferred_title)
    if not preferred_key:
        return ""
    for value in values:
        candidate = str(value or "").strip()
        if candidate and _metadata_compare_text(candidate) == preferred_key:
            return candidate
    return ""


def _part_marker_number(value: str) -> int | None:
    match = re.search(r"\bpart\s*(\d{1,2})\b", value.casefold())
    return int(match.group(1)) if match else None


def _cour_marker_number(value: str) -> int | None:
    normalized = value.casefold()
    match = re.search(r"\bcour\s*(\d{1,2})\b", normalized)
    if match:
        return int(match.group(1))
    match = re.search(r"\b(\d{1,2})(?:st|nd|rd|th)?\s*cour\b", normalized)
    return int(match.group(1)) if match else None


def _map_offline_database_item(item: dict[str, Any]) -> dict[str, Any]:
    season = item.get("animeSeason") or {}
    duration = item.get("duration") or {}
    score = item.get("score") or {}
    year = season.get("year")
    duration_seconds = duration.get("value")
    score_value = score.get("arithmeticMean") or score.get("median")

    title_values = [item.get("title"), *item.get("synonyms", [])]
    return {
        "title": item.get("title") or "Unknown title",
        "original_title": (item.get("synonyms") or ["Unknown"])[0],
        "year": str(year) if year else "Unknown",
        "status": _format_database_status(item.get("status")),
        "episodes": str(item.get("episodes")) if item.get("episodes") is not None else "Unknown",
        "season_number": _infer_season_number(title_values),
        "runtime": _format_duration_seconds(duration_seconds),
        "genres": _title_case_values(item.get("tags", [])[:8]),
        "aliases": _unique_values(title_values),
        "studio": ", ".join(_title_case_values(item.get("studios", [])[:2])) or "Unknown",
        "source": "anime-offline-database",
        "rating": f"{round(score_value * 10)}%" if isinstance(score_value, (int, float)) else "Unrated",
        "synopsis": "Offline metadata entry. Live synopsis can be enriched from AniList, Kitsu, or TMDB.",
        "poster": item.get("picture") or item.get("thumbnail") or "",
        "air_date": "",
        "next_airing_at": "",
        "airing_episode": "",
        "airing_source": "",
        "provider_ids": _extract_provider_ids(item.get("sources", [])),
    }


def _map_kitsu_item(item: dict[str, Any]) -> dict[str, Any]:
    attributes = item.get("attributes") or {}
    titles = attributes.get("titles") or {}
    poster = attributes.get("posterImage") or {}
    episode_count = attributes.get("episodeCount")
    episode_length = attributes.get("episodeLength")
    rating = attributes.get("averageRating")
    start_date = attributes.get("startDate") or ""
    airing = _date_airing_fields(start_date, "Kitsu")

    title_values = [
        titles.get("en"),
        titles.get("en_jp"),
        titles.get("ja_jp"),
        attributes.get("canonicalTitle"),
    ]
    return {
        "title": titles.get("en") or attributes.get("canonicalTitle") or "Unknown title",
        "original_title": titles.get("en_jp") or attributes.get("canonicalTitle") or "Unknown",
        "year": start_date[:4] if start_date else "Unknown",
        "status": _format_database_status(attributes.get("status")),
        "episodes": str(episode_count) if episode_count else "Unknown",
        "season_number": _infer_season_number(title_values),
        "runtime": f"{episode_length} min" if episode_length else "Unknown",
        "genres": [],
        "aliases": _unique_values(title_values),
        "studio": "Unknown",
        "source": "Kitsu",
        "rating": f"{round(float(rating))}%" if rating else "Unrated",
        "synopsis": attributes.get("synopsis") or "No synopsis available.",
        "poster": poster.get("medium") or poster.get("large") or poster.get("original") or "",
        **airing,
        "provider_ids": {
            "kitsu": item.get("id"),
        },
    }


def _map_tmdb_item(item: dict[str, Any]) -> dict[str, Any]:
    first_air_date = item.get("first_air_date") or ""
    year = first_air_date[:4] if first_air_date else "Unknown"
    vote_average = item.get("vote_average")
    poster_path = item.get("poster_path")
    airing = _date_airing_fields(first_air_date, "TMDB")

    return {
        "title": item.get("name") or "Unknown title",
        "original_title": item.get("original_name") or "Unknown",
        "year": year,
        "status": "Unknown",
        "episodes": "Unknown",
        "season_number": _infer_season_number([item.get("name"), item.get("original_name")]),
        "runtime": "Unknown",
        "genres": [],
        "aliases": _unique_values([item.get("name"), item.get("original_name")]),
        "studio": "Unknown",
        "source": "TMDB",
        "rating": f"{round(vote_average * 10)}%" if isinstance(vote_average, (int, float)) else "Unrated",
        "synopsis": item.get("overview") or "No synopsis available.",
        "poster": f"{TMDB_IMAGE_BASE_URL}{poster_path}" if poster_path else "",
        **airing,
        "provider_ids": {
            "tmdb": item.get("id"),
        },
    }


def _clean_description(description: str) -> str:
    without_tags = re.sub(r"<[^>]+>", "", description)
    return unescape(without_tags).replace("\n", " ").strip()


def _anilist_airing_fields(next_airing: Any) -> dict[str, str]:
    if not isinstance(next_airing, dict):
        return {
            "air_date": "",
            "next_airing_at": "",
            "airing_episode": "",
            "airing_source": "",
        }

    airing_at = next_airing.get("airingAt")
    if not isinstance(airing_at, int) or airing_at <= 0:
        return {
            "air_date": "",
            "next_airing_at": "",
            "airing_episode": "",
            "airing_source": "",
        }

    airing_datetime = datetime.fromtimestamp(airing_at, timezone.utc)
    episode = next_airing.get("episode")
    return {
        "air_date": airing_datetime.date().isoformat(),
        "next_airing_at": airing_datetime.isoformat().replace("+00:00", "Z"),
        "airing_episode": str(episode) if episode else "",
        "airing_source": "AniList",
    }


def _date_airing_fields(value: Any, source: str) -> dict[str, str]:
    empty = {
        "air_date": "",
        "next_airing_at": "",
        "airing_episode": "",
        "airing_source": "",
    }
    if not isinstance(value, str) or not value:
        return empty
    try:
        air_date = datetime.strptime(value[:10], "%Y-%m-%d").date()
    except ValueError:
        return empty
    if air_date < date.today():
        return empty
    return {
        "air_date": air_date.isoformat(),
        "next_airing_at": "",
        "airing_episode": "",
        "airing_source": source,
    }


def _format_anilist_status(status: str | None) -> str:
    if not status:
        return "Unknown"
    return status.replace("_", " ").title()


def _offline_database_path() -> Path | None:
    configured_path = os.environ.get("ANIME_OFFLINE_DATABASE_PATH", "").strip()
    if configured_path:
        path = Path(configured_path)
        return path if path.exists() else None

    for path in OFFLINE_DATABASE_PATHS:
        if path.exists():
            return path

    return None


def refresh_offline_database_cache() -> Path | None:
    return _ensure_offline_database_cache()


def _ensure_offline_database_cache() -> Path | None:
    if OFFLINE_CACHE_FILE.exists() and not _offline_cache_is_stale():
        return OFFLINE_CACHE_FILE

    try:
        release = _get_json(ANIME_OFFLINE_DATABASE_RELEASE_URL, {}, "anime-offline-database release check failed")
        asset = _release_asset(release, "anime-offline-database-minified.json")
        if asset is None:
            raise MetadataProviderError("anime-offline-database release did not include a minified JSON asset.")

        current_metadata = _read_offline_cache_metadata()
        latest_tag = release.get("tag_name")
        if (
            OFFLINE_CACHE_FILE.exists()
            and current_metadata.get("release_tag") == latest_tag
            and current_metadata.get("asset_name") == asset.get("name")
        ):
            _write_offline_cache_metadata(current_metadata | {"checked_at": time()})
            return OFFLINE_CACHE_FILE

        _download_offline_database_asset(asset["browser_download_url"])
        _write_offline_cache_metadata(
            {
                "asset_name": asset.get("name"),
                "checked_at": time(),
                "downloaded_at": time(),
                "release_tag": latest_tag,
                "source_url": asset.get("browser_download_url"),
            }
        )
        _clear_offline_database_memory_cache()
        return OFFLINE_CACHE_FILE
    except MetadataProviderError:
        if OFFLINE_CACHE_FILE.exists():
            return OFFLINE_CACHE_FILE
        return None


def _offline_cache_is_stale() -> bool:
    metadata = _read_offline_cache_metadata()
    checked_at = metadata.get("checked_at", 0)
    return not isinstance(checked_at, (int, float)) or time() - checked_at >= OFFLINE_CACHE_MAX_AGE_SECONDS


def _read_offline_cache_metadata() -> dict[str, Any]:
    try:
        with OFFLINE_CACHE_METADATA_FILE.open("r", encoding="utf-8") as metadata_file:
            metadata = json.load(metadata_file)
            return metadata if isinstance(metadata, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_offline_cache_metadata(metadata: dict[str, Any]) -> None:
    OFFLINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with OFFLINE_CACHE_METADATA_FILE.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, indent=2, sort_keys=True)
        metadata_file.write("\n")


def _release_asset(release: dict[str, Any], asset_name: str) -> dict[str, Any] | None:
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name and asset.get("browser_download_url"):
            return asset
    return None


def _download_offline_database_asset(url: str) -> None:
    OFFLINE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = OFFLINE_CACHE_FILE.with_suffix(".json.tmp")
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/octet-stream",
            "User-Agent": "nyaarr/0.1",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS * 6) as response:
            with temp_path.open("wb") as temp_file:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    temp_file.write(chunk)
        os.replace(temp_path, OFFLINE_CACHE_FILE)
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        raise MetadataProviderError(f"anime-offline-database download failed: {exc}.") from exc


def _load_offline_database(database_path: Path) -> dict[str, Any]:
    global _offline_database_cache
    global _offline_database_cache_mtime
    global _offline_database_cache_path

    resolved_path = database_path.resolve()
    current_mtime = database_path.stat().st_mtime
    if (
        _offline_database_cache is not None
        and _offline_database_cache_path == resolved_path
        and _offline_database_cache_mtime == current_mtime
    ):
        return _offline_database_cache

    with database_path.open("r", encoding="utf-8") as database_file:
        database = json.load(database_file)

    _offline_database_cache = database
    _offline_database_cache_path = resolved_path
    _offline_database_cache_mtime = current_mtime
    return database


def _clear_offline_database_memory_cache() -> None:
    global _offline_database_cache
    global _offline_database_cache_mtime
    global _offline_database_cache_path

    _offline_database_cache = None
    _offline_database_cache_path = None
    _offline_database_cache_mtime = None


def _format_database_status(status: str | None) -> str:
    if not status:
        return "Unknown"
    return status.replace("_", " ").title()


def _format_duration_seconds(seconds: Any) -> str:
    if not isinstance(seconds, int) or seconds <= 0:
        return "Unknown"
    minutes = round(seconds / 60)
    return f"{minutes} min"


def _infer_season_number(values: list[Any]) -> int:
    for value in values:
        if not value:
            continue
        normalized = str(value).casefold()
        match = re.search(r"\b(?:season|s)\s*(\d{1,2})\b", normalized)
        if match:
            return int(match.group(1))
        match = re.search(r"\b(?:part|cour)\s*(\d{1,2})\b", normalized)
        if match:
            return int(match.group(1))
        match = re.search(r"\b(?:ii|2nd)\b", normalized)
        if match:
            return 2
        match = re.search(r"\b(?:iii|3rd)\b", normalized)
        if match:
            return 3
    return 1


def _title_case_values(values: list[str]) -> list[str]:
    return [value.replace("_", " ").title() for value in values if value]


def _extract_provider_ids(sources: list[str]) -> dict[str, str]:
    provider_ids: dict[str, str] = {}
    patterns = {
        "anilist": r"anilist\.co/anime/(\d+)",
        "mal": r"myanimelist\.net/anime/(\d+)",
        "kitsu": r"kitsu\.app/anime/(\d+)",
        "anidb": r"anidb\.net/anime/(\d+)",
    }

    for source in sources:
        for provider, pattern in patterns.items():
            match = re.search(pattern, source)
            if match:
                provider_ids[provider] = match.group(1)

    return provider_ids


def _unique_values(values: list[Any]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value:
            continue
        text = str(value).strip()
        key = text.casefold()
        if text and key not in seen:
            seen.add(key)
            unique.append(text)
    return unique


def clear_runtime_caches() -> None:
    _SEARCH_CACHE.clear()
