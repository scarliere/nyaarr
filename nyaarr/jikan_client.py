from __future__ import annotations

import concurrent.futures
import copy
import json
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Any

from .metrics import timed
from .models import EpisodeTitleRecord, JikanEpisodePage


JIKAN_API_URL = "https://api.jikan.moe/v4"
JIKAN_TIMEOUT_SECONDS = float(os.environ.get("NYAARR_JIKAN_HTTP_TIMEOUT_SECONDS", "12"))
JIKAN_REQUEST_INTERVAL_SECONDS = max(
    1.0,
    float(os.environ.get("NYAARR_JIKAN_REQUEST_INTERVAL_SECONDS", "1.05")),
)
JIKAN_RESPONSE_CACHE_TTL_SECONDS = max(
    0,
    int(os.environ.get("NYAARR_JIKAN_RESPONSE_CACHE_TTL_SECONDS", "300")),
)


class JikanClientError(RuntimeError):
    pass


class JikanRateLimitError(JikanClientError):
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = max(int(retry_after), 1)


class JikanNotFoundError(JikanClientError):
    pass


class JikanClient:
    """Small public-Jikan adapter with one global request lane."""

    def __init__(
        self,
        *,
        timeout_seconds: float = JIKAN_TIMEOUT_SECONDS,
        request_interval_seconds: float = JIKAN_REQUEST_INTERVAL_SECONDS,
        cache_ttl_seconds: int = JIKAN_RESPONSE_CACHE_TTL_SECONDS,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.request_interval_seconds = max(request_interval_seconds, 1.0)
        self.cache_ttl_seconds = max(cache_ttl_seconds, 0)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._inflight: dict[str, concurrent.futures.Future[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._request_lock = threading.Lock()
        self._next_request_at = 0.0
        self._limited_until = 0.0

    def fetch_episode_page(self, mal_id: Any, *, page: int = 1) -> JikanEpisodePage:
        try:
            selected_id = int(str(mal_id).strip())
            selected_page = max(int(page), 1)
        except (TypeError, ValueError) as exc:
            raise JikanClientError("Jikan episode request has an invalid MAL ID or page.") from exc
        if selected_id <= 0:
            raise JikanClientError("Jikan episode request has an invalid MAL ID.")
        payload = self._get_json(f"/anime/{selected_id}/episodes?page={selected_page}")
        pagination = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        values = payload.get("data") if isinstance(payload.get("data"), list) else []
        fetched_at = _utc_now()
        records: list[EpisodeTitleRecord] = []
        for value in values:
            if not isinstance(value, dict):
                continue
            episode = _positive_int(value.get("mal_id"))
            if episode is None:
                continue
            records.append(
                {
                    "provider": "jikan",
                    "mal_id": str(selected_id),
                    "episode": episode,
                    "title": _text(value.get("title")),
                    "title_japanese": _text(value.get("title_japanese")),
                    "title_romanji": _text(value.get("title_romanji")),
                    "aired_at": _aired_at(value.get("aired")),
                    "filler": bool(value.get("filler")),
                    "recap": bool(value.get("recap")),
                    "fetched_at": fetched_at,
                }
            )
        return {
            "mal_id": str(selected_id),
            "page": selected_page,
            "last_visible_page": max(_positive_int(pagination.get("last_visible_page")) or selected_page, selected_page),
            "has_next_page": bool(pagination.get("has_next_page")),
            "records": records,
            "fetched_at": fetched_at,
        }

    def _get_json(self, path: str) -> dict[str, Any]:
        now = time.time()
        with self._lock:
            cached = self._cache.get(path)
            if cached is not None and now - cached[0] < self.cache_ttl_seconds:
                return copy.deepcopy(cached[1])
            if now < self._limited_until:
                raise JikanRateLimitError(
                    "Jikan request deferred by the provider rate limit.",
                    int(self._limited_until - now) + 1,
                )
            future = self._inflight.get(path)
            owns_request = future is None
            if future is None:
                future = concurrent.futures.Future()
                self._inflight[path] = future
        if owns_request:
            try:
                result = self._request(path)
                with self._lock:
                    self._cache[path] = (now, copy.deepcopy(result))
                    self._prune_cache(now)
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                with self._lock:
                    self._inflight.pop(path, None)
        try:
            return copy.deepcopy(future.result(timeout=self.timeout_seconds + self.request_interval_seconds + 2))
        except concurrent.futures.TimeoutError as exc:
            raise JikanClientError("Jikan shared request timed out.") from exc

    def _request(self, path: str) -> dict[str, Any]:
        with self._request_lock:
            delay = self._next_request_at - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            self._next_request_at = time.monotonic() + self.request_interval_seconds
            request = urllib.request.Request(
                f"{JIKAN_API_URL}{path}",
                headers={"Accept": "application/json", "User-Agent": "nyaarr/0.1"},
                method="GET",
            )
            try:
                with timed("provider.jikan"):
                    with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                        return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    raise JikanNotFoundError("Jikan has no episode data for this MAL ID.") from exc
                if exc.code == 429:
                    retry_after = _header_int(exc.headers, "Retry-After") or 60
                    with self._lock:
                        self._limited_until = max(self._limited_until, time.time() + retry_after)
                    raise JikanRateLimitError("Jikan rate limit reached.", retry_after) from exc
                raise JikanClientError(f"Jikan request failed: HTTP {exc.code}.") from exc
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise JikanClientError(f"Jikan request failed: {exc}.") from exc

    def _prune_cache(self, now: float) -> None:
        expired = [
            key for key, (stored_at, _value) in self._cache.items()
            if now - stored_at >= max(self.cache_ttl_seconds, 1)
        ]
        for key in expired:
            self._cache.pop(key, None)
        while len(self._cache) > 128:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)


def _positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _aired_at(value: Any) -> str:
    text = _text(value)
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _header_int(headers: Any, name: str) -> int | None:
    try:
        return int(headers.get(name))
    except (AttributeError, TypeError, ValueError):
        return None


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


client = JikanClient()
