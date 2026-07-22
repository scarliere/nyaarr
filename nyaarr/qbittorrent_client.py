from __future__ import annotations

import json
import hashlib
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar
from typing import Any

from .metrics import timed


_CLIENT_CACHE_TTL_SECONDS = 5 * 60
_CLIENT_CACHE: dict[str, tuple[float, 'QBittorrentClient']] = {}
_CLIENT_CACHE_LOCK = threading.RLock()


class QBittorrentError(RuntimeError):
    pass


class QBittorrentClient:
    def __init__(self, settings: dict[str, Any], timeout: int = 10) -> None:
        self.settings = settings
        self.timeout = timeout
        self.base_url = self._base_url(settings)
        if not self.base_url:
            raise QBittorrentError("The configured qBittorrent host or port is invalid.")
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(CookieJar()))
        self._request_lock = threading.RLock()

    def login(self) -> None:
        username = str(self.settings.get("username") or "")
        password = str(self.settings.get("password") or "")
        if not username and not password:
            return

        response = self._request(
            "/api/v2/auth/login",
            data={"username": username, "password": password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if response.decode("utf-8", errors="replace").strip() != "Ok.":
            raise QBittorrentError("qBittorrent rejected the saved username or password.")

    def version(self) -> str:
        return self._request("/api/v2/app/version", method="GET").decode("utf-8", errors="replace").strip()

    def add_url(
        self,
        url: str,
        *,
        save_path: str,
        category: str,
        tags: str,
        rename: str | None = None,
        paused: bool = False,
        root_folder: bool = True,
        expected_infohash: str = "",
    ) -> bool:
        fields = {
            "urls": url,
            "savepath": save_path,
            "category": category,
            "tags": tags,
            "paused": _bool_value(paused),
            "root_folder": _bool_value(root_folder),
            "autoTMM": "false",
        }
        if rename:
            fields["rename"] = rename
        response = self._multipart_request("/api/v2/torrents/add", fields)
        result = response.decode("utf-8", errors="replace").strip()
        if result != "Ok.":
            detail = result or "empty response"
            raise QBittorrentError(f"qBittorrent rejected the torrent add request: {detail}")
        normalized_hash = str(expected_infohash or "").strip().casefold()
        if normalized_hash:
            return self._wait_for_torrent(normalized_hash)
        return True

    def _wait_for_torrent(self, torrent_hash: str, attempts: int = 4) -> bool:
        for attempt in range(max(attempts, 1)):
            if self.torrents(hashes=torrent_hash):
                return True
            if attempt + 1 < attempts:
                time.sleep(0.25 * (attempt + 1))
        return False

    def torrents(self, *, category: str = "", hashes: str = "") -> list[dict[str, Any]]:
        query = {}
        if category:
            query["category"] = category
        if hashes:
            query["hashes"] = hashes
        suffix = f"?{urllib.parse.urlencode(query)}" if query else ""
        raw = self._request(f"/api/v2/torrents/info{suffix}", method="GET")
        try:
            result = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QBittorrentError(f"qBittorrent returned invalid torrent list JSON: {exc}.") from exc
        return result if isinstance(result, list) else []

    def torrent_files(self, torrent_hash: str) -> list[dict[str, Any]]:
        suffix = urllib.parse.urlencode({"hash": torrent_hash})
        raw = self._request(f"/api/v2/torrents/files?{suffix}", method="GET")
        try:
            result = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise QBittorrentError(f"qBittorrent returned invalid torrent file JSON: {exc}.") from exc
        return result if isinstance(result, list) else []

    def set_file_priority(self, torrent_hash: str, indexes: list[int], priority: int) -> None:
        if not indexes:
            return
        self._request(
            "/api/v2/torrents/filePrio",
            data={
                "hash": torrent_hash,
                "id": "|".join(str(index) for index in indexes),
                "priority": str(priority),
            },
        )

    def resume(self, torrent_hash: str) -> None:
        try:
            self._request("/api/v2/torrents/resume", data={"hashes": torrent_hash})
        except QBittorrentError as exc:
            if "HTTP 404" not in str(exc):
                raise
            self._request("/api/v2/torrents/start", data={"hashes": torrent_hash})

    def delete(self, torrent_hash: str, *, delete_files: bool = False) -> None:
        self._request(
            "/api/v2/torrents/delete",
            data={"hashes": torrent_hash, "deleteFiles": _bool_value(delete_files)},
        )

    def rename_folder(self, torrent_hash: str, old_path: str, new_path: str) -> None:
        self._request(
            "/api/v2/torrents/renameFolder",
            data={"hash": torrent_hash, "oldPath": old_path, "newPath": new_path},
        )

    def set_location(self, torrent_hash: str, location: str) -> None:
        self._request("/api/v2/torrents/setLocation", data={"hashes": torrent_hash, "location": location})

    def _request(
        self,
        path: str,
        *,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        method: str = "POST",
    ) -> bytes:
        body = None
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "User-Agent": "nyaarr/0.1",
                "Referer": self.base_url,
                **(headers or {}),
            },
            method=method,
        )
        try:
            with timed('provider.qbittorrent'):
                with self._request_lock:
                    with self.opener.open(request, timeout=self.timeout) as response:
                        return response.read()
        except urllib.error.HTTPError as exc:
            raise QBittorrentError(f"qBittorrent request failed: HTTP {exc.code}.") from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise QBittorrentError(f"qBittorrent request failed: {exc}.") from exc

    def _multipart_request(self, path: str, fields: dict[str, str]) -> bytes:
        boundary = "----NyaarrFormBoundary7MA4YWxkTrZu0gW"
        chunks: list[bytes] = []
        for name, value in fields.items():
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode("utf-8"),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                    str(value).encode("utf-8"),
                    b"\r\n",
                ]
            )
        chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=b"".join(chunks),
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "nyaarr/0.1",
                "Referer": self.base_url,
            },
            method="POST",
        )
        try:
            with timed('provider.qbittorrent'):
                with self._request_lock:
                    with self.opener.open(request, timeout=self.timeout) as response:
                        return response.read()
        except urllib.error.HTTPError as exc:
            raise QBittorrentError(f"qBittorrent request failed: HTTP {exc.code}.") from exc
        except (OSError, TimeoutError, urllib.error.URLError) as exc:
            raise QBittorrentError(f"qBittorrent request failed: {exc}.") from exc

    @staticmethod
    def _base_url(settings: dict[str, Any]) -> str:
        host = str(settings.get("host") or "").strip()
        try:
            port = int(str(settings.get("port") or "").strip())
        except ValueError:
            return ""
        if not host or not 1 <= port <= 65535:
            return ""
        scheme = "https" if settings.get("use_ssl") else "http"
        url_base = str(settings.get("url_base") or "").strip().strip("/")
        base_url = f"{scheme}://{host}:{port}"
        if url_base:
            base_url = f"{base_url}/{url_base}"
        return base_url.rstrip("/")


def client_from_settings(settings: dict[str, Any], timeout: int = 10) -> QBittorrentClient:
    client_settings = settings.get("download_client")
    if not isinstance(client_settings, dict) or client_settings.get("implementation") != "qbittorrent":
        raise QBittorrentError("No supported qBittorrent client is configured.")
    if not client_settings.get("enabled"):
        raise QBittorrentError("The configured qBittorrent client is disabled.")
    cache_key = hashlib.sha256(json.dumps(client_settings, sort_keys=True, default=str).encode('utf-8')).hexdigest()
    now = time.monotonic()
    with _CLIENT_CACHE_LOCK:
        cached = _CLIENT_CACHE.get(cache_key)
        if cached is not None and now - cached[0] < _CLIENT_CACHE_TTL_SECONDS:
            cached[1].timeout = timeout
            _CLIENT_CACHE[cache_key] = (now, cached[1])
            return cached[1]
        client = QBittorrentClient(client_settings, timeout=timeout)
        client.login()
        _CLIENT_CACHE.clear()
        _CLIENT_CACHE[cache_key] = (now, client)
        return client


def clear_client_cache() -> None:
    with _CLIENT_CACHE_LOCK:
        _CLIENT_CACHE.clear()


def _bool_value(value: bool) -> str:
    return "true" if value else "false"
