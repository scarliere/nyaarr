# Jikan Episode Titles

Jikan is a best-effort enrichment source for episode display titles. It is not
used for anime identity, air dates, aired-episode eligibility, torrent search,
or download dispatch.

## Flow

AniList remains the primary metadata service and supplies the MyAnimeList ID in
`provider_ids.mal`. Nyaarr passes that ID directly to:

```text
GET https://api.jikan.moe/v4/anime/{mal_id}/episodes?page={page}
```

There is no Jikan title search and no per-episode callback. Each response stores
up to 100 episode rows, and durable `jikan_episode_titles` jobs continue through
`pagination.has_next_page`.

`nyaarr/episode_title_repository.py` stores English, romanized, and Japanese
titles in the shared SQLite database under `episode_titles`. Empty provider
values cannot overwrite an existing non-empty title. A separate sync row makes
pagination idempotent and prevents an open detail page from restarting page 1.

Anime Detail reads SQLite only. If the cache is due, it renders immediately with
cached titles or `Episode N`, enqueues background hydration, and polls
`/anime/<library_id>/episode-titles` for a bounded number of attempts. Provider
failure therefore does not stall or break the page.

## Rate and retry policy

The public Jikan limit is 3 requests per second and 60 requests per minute, with
additional upstream MyAnimeList rate limiting possible. `nyaarr/jikan_client.py`
uses one process-wide request lane with a default 1.05-second start interval,
short response caching, and identical-request coalescing.

HTTP 429 honors `Retry-After` through the durable job queue. Timeouts and 5xx
responses use the queue's bounded exponential retries. A 404 marks the cache
complete with its existing rows instead of retrying indefinitely.

Configuration:

- `NYAARR_JIKAN_HTTP_TIMEOUT_SECONDS`: request timeout, default 12 seconds.
- `NYAARR_JIKAN_REQUEST_INTERVAL_SECONDS`: clamped to at least 1 second,
  default 1.05 seconds.
- `NYAARR_JIKAN_RESPONSE_CACHE_TTL_SECONDS`: memory cache, default 5 minutes.
- `NYAARR_JIKAN_ONGOING_TITLE_REFRESH_MAX_AGE_SECONDS`: default 6 hours.
- `NYAARR_JIKAN_FINISHED_TITLE_REFRESH_MAX_AGE_SECONDS`: default 30 days.

## Display selection and limitations

The episode table prefers Jikan's English `title`, then `title_romanji`, then
`title_japanese`, and finally `Episode N`. Cached partial results are useful
and remain visible while later pages or retries run.

Jikan is an unofficial MyAnimeList scraper/cache. Current or obscure episode
titles can be null, delayed, or unavailable during Jikan/MAL outages. Persistent
caching improves continuity but does not turn Jikan into an authoritative
service; Nyaarr deliberately keeps every operational decision on AniList and
local state.
