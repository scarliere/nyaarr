from __future__ import annotations

import concurrent.futures
import copy
import json
import threading
import time
import urllib.error
import urllib.request
from typing import Any


ANILIST_URL = "https://graphql.anilist.co"


class AniListClientError(RuntimeError):
    pass


class AniListRateLimitError(AniListClientError):
    def __init__(self, message: str, retry_after: int = 60) -> None:
        super().__init__(message)
        self.retry_after = max(int(retry_after), 1)


class AniListClient:
    def __init__(self, *, timeout_seconds: float = 10, cache_ttl_seconds: int = 300) -> None:
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self._inflight: dict[str, concurrent.futures.Future[dict[str, Any]]] = {}
        self._lock = threading.RLock()
        self._limited_until = 0.0

    def execute(
        self,
        query: str,
        variables: dict[str, Any] | None = None,
        *,
        cache_ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        key = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        now = time.time()
        ttl = self.cache_ttl_seconds if cache_ttl_seconds is None else max(cache_ttl_seconds, 0)
        with self._lock:
            if now < self._limited_until:
                raise AniListRateLimitError(
                    "AniList request deferred by the provider rate limit.",
                    int(self._limited_until - now) + 1,
                )
            cached = self._cache.get(key)
            if cached is not None and now - cached[0] < ttl:
                return copy.deepcopy(cached[1])
            future = self._inflight.get(key)
            owns_request = future is None
            if future is None:
                future = concurrent.futures.Future()
                self._inflight[key] = future
        if owns_request:
            try:
                result = self._post(payload)
                with self._lock:
                    self._cache[key] = (now, copy.deepcopy(result))
                    self._prune_cache(now)
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            finally:
                with self._lock:
                    self._inflight.pop(key, None)
        try:
            return copy.deepcopy(future.result(timeout=self.timeout_seconds + 2))
        except concurrent.futures.TimeoutError as exc:
            raise AniListClientError("AniList shared request timed out.") from exc

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            ANILIST_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": "nyaarr/0.1",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                retry_after = _header_int(exc.headers, "Retry-After") or 60
                with self._lock:
                    self._limited_until = max(self._limited_until, time.time() + retry_after)
                raise AniListRateLimitError("AniList rate limit reached.", retry_after) from exc
            raise AniListClientError(f"AniList request failed: HTTP {exc.code}.") from exc
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise AniListClientError(f"AniList request failed: {exc}.") from exc

    def _prune_cache(self, now: float) -> None:
        expired = [
            key for key, (stored_at, _value) in self._cache.items()
            if now - stored_at >= max(self.cache_ttl_seconds, 1)
        ]
        for key in expired:
            self._cache.pop(key, None)
        while len(self._cache) > 256:
            oldest = min(self._cache, key=lambda key: self._cache[key][0])
            self._cache.pop(oldest, None)


def _header_int(headers: Any, name: str) -> int | None:
    try:
        return int(headers.get(name))
    except (AttributeError, TypeError, ValueError):
        return None


client = AniListClient()
