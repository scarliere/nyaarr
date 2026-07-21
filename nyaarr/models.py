from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict


class RawNyaaMetadata(TypedDict, total=False):
    title: str
    link: str
    guid: str
    published: str
    category: str
    category_id: str
    size: str
    infohash: str


class ParsedReleaseMetadata(TypedDict, total=False):
    release_group: str
    release_kind: Literal["episode", "batch", "unknown"] | str
    episode: int | None
    source_kind: str
    resolution: int | None
    confidence: int
    rejection_reasons: list[str]


class NyaaRelease(TypedDict, total=False):
    raw_title: str
    title: str
    detail_url: str
    torrent_url: str
    guid: str
    published: str
    seeders: int
    leechers: int
    downloads: int
    infohash: str
    category: str
    category_id: str
    size: str
    size_bytes: int
    trusted: str
    remake: str
    comments: int
    raw: RawNyaaMetadata
    parsed: ParsedReleaseMetadata
    release_group: str
    release_group_source: str
    release_kind: str
    episode: int | None
    source_kind: str
    resolution: int | None
    confidence: NotRequired[int]
    confidence_reasons: NotRequired[list[str]]
    batch_verification: NotRequired["BatchVerification"]
    batch_fallback_episodes: NotRequired[list[int]]


class JobOutcome(TypedDict, total=False):
    status: Literal["ok", "skipped", "failed"]
    changed: bool
    message: str
    metrics: dict[str, int | float | str | bool | None]


class DownloadQueueRecord(TypedDict, total=False):
    status: str
    client: str
    category: str
    hash: str
    title: str
    torrent_url: str
    release_kind: str
    release_group: str
    episode: int | None
    wanted_episodes: list[int]
    safety_status: str
    import_status: str
    progress: int
    message: str
    queued_at: str
    completed_at: str
    raw: dict[str, Any]


class EpisodeAiringRecord(TypedDict, total=False):
    provider: str
    media_id: str
    episode: int
    airing_at: str
    precision: Literal["exact", "estimated"]
    inference_source: str
    fetched_at: str


class AniListSnapshot(TypedDict, total=False):
    media: dict[str, Any]
    past_airings: list[EpisodeAiringRecord]
    future_airings: list[EpisodeAiringRecord]


class BatchVerification(TypedDict, total=False):
    status: Literal["verified", "rejected", "unavailable"]
    wanted_episodes: list[int]
    covered_episodes: list[int]
    uncovered_episodes: list[int]
    dangerous_files: list[str]
    verified_at: str
    source: str
    reason: str


class EpisodeTitleRecord(TypedDict, total=False):
    provider: Literal["jikan"]
    mal_id: str
    episode: int
    title: str
    title_japanese: str
    title_romanji: str
    aired_at: str
    filler: bool
    recap: bool
    fetched_at: str


class JikanEpisodePage(TypedDict, total=False):
    mal_id: str
    page: int
    last_visible_page: int
    has_next_page: bool
    records: list[EpisodeTitleRecord]
    fetched_at: str
