from __future__ import annotations

from typing import Any


STATUS_FILTERS = {
    "all": "All statuses",
    "finished": "Finished",
    "releasing": "Releasing",
    "not_yet_released": "Not yet released",
    "cancelled": "Cancelled",
    "hiatus": "Hiatus",
    "unknown": "Unknown",
}

SORT_OPTIONS = {
    "relevance": "Relevance",
    "title": "Title",
    "year_desc": "Year newest",
    "year_asc": "Year oldest",
    "rating_desc": "Rating highest",
    "episodes_desc": "Episodes most",
}


def apply_result_controls(
    results: list[dict[str, Any]],
    status_filter: str,
    sort_key: str,
) -> list[dict[str, Any]]:
    filtered_results = _filter_by_status(results, status_filter)
    return _sort_results(filtered_results, sort_key)


def normalize_status_filter(value: str) -> str:
    return value if value in STATUS_FILTERS else "all"


def normalize_sort_key(value: str) -> str:
    return value if value in SORT_OPTIONS else "relevance"


def _filter_by_status(results: list[dict[str, Any]], status_filter: str) -> list[dict[str, Any]]:
    if status_filter == "all":
        return results

    return [
        result
        for result in results
        if _status_slug(str(result.get("status", "Unknown"))) == status_filter
    ]


def _sort_results(results: list[dict[str, Any]], sort_key: str) -> list[dict[str, Any]]:
    if sort_key == "title":
        return sorted(results, key=lambda result: str(result.get("title", "")).casefold())
    if sort_key == "year_desc":
        return sorted(results, key=_year_value, reverse=True)
    if sort_key == "year_asc":
        return sorted(results, key=_year_value)
    if sort_key == "rating_desc":
        return sorted(results, key=_rating_value, reverse=True)
    if sort_key == "episodes_desc":
        return sorted(results, key=_episode_value, reverse=True)

    return results


def _status_slug(status: str) -> str:
    return status.strip().casefold().replace(" ", "_").replace("-", "_")


def _year_value(result: dict[str, Any]) -> int:
    try:
        return int(str(result.get("year", "0")))
    except ValueError:
        return 0


def _rating_value(result: dict[str, Any]) -> int:
    rating = str(result.get("rating", "")).strip().rstrip("%")
    try:
        return int(float(rating))
    except ValueError:
        return 0


def _episode_value(result: dict[str, Any]) -> int:
    try:
        return int(str(result.get("episodes", "0")))
    except ValueError:
        return 0
