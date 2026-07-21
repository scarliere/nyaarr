# Airing Schedule Refresh

AniList is the source of truth for episode air dates. `nyaarr/anilist_client.py` owns GraphQL transport, short-lived response caching, identical-request coalescing, and provider rate-limit state. One periodic snapshot per due library item updates both normalized metadata and schedule state; the general external-maintenance lane no longer makes a second AniList metadata callback.

The snapshot stores exact recent past and future `AiringSchedule` rows in the indexed `anime_airings` SQLite table through `nyaarr/airing_repository.py`. The library record keeps the compact operational projection: `aired_episode`, `next_airing_at`, `airing_episode`, `airing_source`, and check timestamps. Download planning uses only exact past airings. A stale next-airing pointer is cleared after its timestamp passes even when AniList still reports the series as releasing.

The schedule refresh age defaults to 15 minutes through `NYAARR_AIRING_REFRESH_MAX_AGE_SECONDS`; each job checks at most 10 items by default through `NYAARR_MAX_AIRING_REFRESHES_PER_TICK`. AniList HTTP 429 responses propagate `Retry-After` into the durable job queue instead of spinning or sleeping a worker.

When at least three recent exact dates establish a stable weekly cadence, Nyaarr may backfill missing older rows as `precision=estimated`. Estimates are labeled in the calendar/detail UI and are display-only: they never increase `aired_episode` or make an episode eligible for torrent search.

AniChart does not need a separate adapter. AniList's official API repository states that AniList and AniChart both run on the same GraphQL API, and AniList exposes the full airing schedule there. Using the shared AniList client avoids a duplicate service, callback, cache, and failure mode.

Library completion remains file-based: an anime becomes `library_state = Completed` only when provider status is finished and all expected episode files are present.
