# Metadata Providers

Add Anime metadata search is implemented in `nyaarr/metadata.py`.

## Provider Order

`search_anime_metadata(query)` tries providers in this order:

1. AniList live GraphQL API
2. anime-offline-database managed local cache
3. Kitsu live JSON:API
4. TMDB live API, only when configured

The first provider that returns results wins. Provider errors are collected as notices and can be rendered in the UI.

## AniList

- Function: `search_anilist`
- Endpoint: `https://graphql.anilist.co`
- Authentication: none for public metadata search
- Role: primary provider

Requested fields include:

- AniList ID
- MAL ID
- romaji, English, and native titles
- description
- season year
- status
- episode count
- duration
- average score
- genres
- cover image
- main studio
- media format, release season, start/end dates, country, source material, adult flag, and provider update time
- exact recent past/future episode airing rows

`fetch_anilist_snapshot()` combines those fields with recent past and future schedules in one GraphQL callback per library item. `fetch_anilist_airing_window()` is reserved for lazy Calendar month hydration. Both use the shared `AniListClient`, which coalesces identical requests and honors provider `Retry-After` responses.

AniChart is not queried separately: AniList documents that both AniList and AniChart use the AniList GraphQL API. A second AniChart scraper/wrapper would duplicate the same underlying schedule service without adding an independent source.

## Jikan episode-title enrichment

Jikan is outside the Add Anime provider order. It only enriches episode rows
after AniList supplies a MAL ID. Paginated episode lists are fetched in
low-priority durable jobs and persisted in SQLite; page renders never call
Jikan. The UI keeps `Episode N` whenever Jikan is unavailable or has no title.

The adapter serializes requests slightly slower than one per second to respect
both documented public limits: 3 requests per second and 60 requests per minute.
See `knowledgebase/integrations/jikan-episode-titles.md` for cache, retry, and
configuration details.

## anime-offline-database

- Function: `search_anime_offline_database`
- Authentication: none
- Role: first fallback after AniList and cross-provider ID source

Managed cache:

- Cache file: `data/cache/anime-offline-database-minified.json`
- Cache metadata: `data/cache/anime-offline-database-cache.json`
- Release source: latest GitHub release from `manami-project/anime-offline-database`
- Asset: `anime-offline-database-minified.json`
- Update interval: weekly, using `checked_at` in the cache metadata

Override options:

- Set `ANIME_OFFLINE_DATABASE_PATH`
- Or place `anime-offline-database-minified.json` or `anime-offline-database.json` in `data/`

The repo includes `data/.gitkeep` and `data/cache/.gitkeep` so these directories exist without committing large dataset files. `.gitignore` excludes the generated cache files.

Current behavior:

- A low-priority daily job checks the managed cache and downloads it when missing or older than 7 days.
- Interactive search never downloads the dataset; it uses an existing cache or continues to live fallback providers.
- Uses the managed cached JSON first after AniList unless `ANIME_OFFLINE_DATABASE_PATH` is configured.
- Keeps the parsed JSON in memory while the process runs and reloads only if the file mtime changes.
- Searches title and synonyms.
- Returns up to 10 normalized results.
- Extracts known provider IDs from source URLs where possible.

## Kitsu

- Function: `search_kitsu`
- Endpoint: `https://kitsu.app/api/edge/anime`
- Authentication: none for public search
- Role: live no-key fallback

Kitsu requires JSON:API headers:

```text
Accept: application/vnd.api+json
Content-Type: application/vnd.api+json
```

Current behavior:

- Searches with `filter[text]`.
- Returns up to 10 normalized results.
- Maps title, year, status, episode count, runtime, rating, synopsis, poster, and Kitsu ID.

## TMDB

- Function: `search_tmdb`
- Endpoint: `https://api.themoviedb.org/3/search/tv`
- Authentication: required
- Role: optional final fallback, useful for posters/backdrops or broad TV metadata

Configuration:

- `TMDB_BEARER_TOKEN`
- Or `TMDB_API_KEY`

TMDB is intentionally last because it is not anime-native and needs credentials.

## AniList Episode Count Refresh

Periodic maintenance rechecks AniList metadata for every anime with an AniList ID after `NYAARR_ANILIST_METADATA_REFRESH_MAX_AGE_SECONDS`, defaulting to 24 hours. Airing titles can make the same unified snapshot due sooner through the 15-minute schedule refresh age.

When a confident AniList match is found, Nyaarr updates the stored episode count, provider IDs, airing fields, aliases, and completion state. Root-folder imports that initially used fallback providers such as Kitsu are upgraded to AniList when title, year, season, and local episode count checks are compatible.

Local progress only counts files in the selected season folder when a season folder exists, so extras under folders such as `Other` or `Trailers` do not inflate downloaded episode totals. Some providers count recap/special entries such as episode `0` or `.5` in the total; when local files contain a contiguous main run plus those special files, completion uses the main-episode count as the effective download target and stores `episode_count_adjustment` with the provider total. This prevents searches for non-existent final episodes while preserving the provider metadata.

## Root-Folder Match Confidence

Root-folder metadata matching scores the imported folder title against the provider title, original/Romaji title, explicit aliases, metadata search titles, and provider title objects such as AniList `romaji`, `english`, and `native`. Exact alias or Romaji matches can satisfy confidence even when the English display title differs, while year, season, part/cour, and episode-count compatibility still constrain ambiguous matches.

AniList display-title mapping keeps English, Romaji, native, and synonym titles available for matching. When AniList's English title uses `Cour N` but its Romaji title or synonym uses the matching `Part N`, Nyaarr chooses the `Part N` form as the primary title and leaves the `Cour N` form as an alias/provider title. This avoids seeding torrent searches with uncommon cour wording for split-cour anime such as Dr. Stone: Science Future Part 3.
## Poster Repair

The periodic maintenance worker repairs missing or blocked posters outside page render paths. Dashboard and calendar pages never call metadata providers directly for poster repair.

Repair behavior:

- Checks the stored poster URL at most once per `NYAARR_POSTER_CHECK_MAX_AGE_SECONDS`, defaulting to 24 hours.
- If the stored URL loads as an image, the anime is marked with `poster_status=ok`.
- If the stored URL is missing or fails, Nyaarr tries alternate provider metadata using stored provider IDs first, then title/original-title/metadata search titles.
- Provider order for repair is AniList ID lookup, AniList title search, Kitsu title search, then TMDB title search when TMDB is configured.
- A successful repair stores `poster`, `poster_source`, `poster_status=repaired`, and a System Logs metadata event.
- Maintenance caps repair attempts with `NYAARR_MAX_POSTER_REPAIRS_PER_TICK`, defaulting to 3, so bad posters cannot dominate background work.

The browser still keeps the local `default-icon.png` fallback for any poster that fails after render.

## Normalization

All providers map into one dictionary shape for the UI:

- `title`
- `original_title`
- `year`
- `status`
- `episodes`
- `runtime`
- `genres`
- `studio`
- `source`
- `rating`
- `synopsis`
- `poster`
- `provider_ids`

## Verified Searches

Live checks performed:

- AniList search for `frieren` returned 6 results.
- Kitsu direct search for `frieren` returned 6 results.
- Flask route `/add?q=frieren` rendered AniList results.

## Current Limitations

- anime-offline-database search is still a linear scan through the cached dataset; add an index before large-scale use.
- Kitsu mapper does not yet fetch genres or studios through related resources.
- TMDB provider is not tested without credentials in this repo.
- Add Anime searches remain synchronous inside their async page fragment. Library refreshes and Calendar history hydration run as durable background jobs.




## Poster Fallbacks

When a primary metadata provider returns a confident anime match without poster artwork, Nyaarr continues checking fallback providers for a matching result with a poster. Metadata search results are enriched before callers receive them, so Add Anime, root-folder import, manual verification, and background metadata refresh can keep the selected provider identity from the best metadata match while using the poster URL and `poster_source` from an equivalent fallback match. This helps fresh client scans resolve artwork for titles whose AniList result temporarily lacks cover art, such as `SANDA`.

Root-folder imports and poster repair prefer AniList artwork when an AniList ID or confident title match is available, even if a fallback provider already supplied an anime-offline-database or Kitsu poster. Legacy fallback-backed rows are normalized into pending AniList reconciliation so the maintenance worker retries AniList metadata and poster lookup without waiting for stale fallback artwork to fail in the browser.
Zero-episode provider or cache results are not accepted for folders that already contain local episode files. This prevents stale fallback metadata, such as an offline SANDA entry with episodes: 0, from blocking later AniList/Kitsu resolution for a real season folder.
Manual metadata review merges compatible resolved-cache candidates with the stored live-search candidates before rendering and selection. This keeps a known AniList match visible for review when the current live provider search is temporarily rate-limited or only returns anime-offline-database fallback rows.

## AniList Alias Preservation

Add Anime now posts AniList aliases and provider title variants with the selected result. AniList searches prefer an exact matched title or synonym for the visible result title, and later AniList ID refreshes preserve an existing title when it is one of AniList's known title values. Routine and manual AniList refreshes store `source` as `AniList`, while root-folder provider resolution still records its scan context until reconciled.

This keeps titles such as `Daemons of the Shadow Realm` from being replaced by a different synonym after the AniList ID is already known. Current limitation: if AniList does not expose the user's preferred title as a title or synonym, Nyaarr still uses AniList's canonical mapped title.
