# Torrent Finder Process

The torrent finder starts when a user clicks Add on an Add Anime metadata result. Metadata identity is reconciled separately: fallback providers can bootstrap an item, but AniList remains the final source of truth as documented in `knowledgebase/features/anilist-reconciliation-and-nfo.md`.

## Flow

1. User searches `/add?q=<title>`.
2. User clicks Add on a metadata result.
3. The form posts normalized metadata to `/anime`. The user can optionally include a Nyaa view/download link, magnet, or direct `.torrent` URL with the add request.
4. `add_anime_to_library_route()` passes the metadata and optional supplied torrent link to app state.
5. App state checks the configured root folder for already-present episode files.
6. If a supplied torrent link is present, Nyaarr stores it as the first candidate for background qBittorrent dispatch and defers normal searching until later missing episodes need it. Otherwise, `find_torrents_for_anime()` searches nyaa.si RSS after local episode progress is known. When `settings.preferred_subbers` is not empty, preferred-subber queries are tried before generic title queries.
7. If qBittorrent and a root folder are configured, Nyaarr sends selected `.torrent` URLs to qBittorrent paused and stores queue records on the anime. Per-episode torrents use the anime's existing `local_path` as the save path when one is known, so alternate English/romanized release titles do not create duplicate anime folders. A single `download_queue` primary record is retained for compatibility, while `download_queues` tracks every queued per-episode torrent.
8. Queue refresh reads qBittorrent torrent file metadata for every active queue record before allowing torrents to run. Only known anime video container files pass automatically.
9. The Anime List dashboard shows episode progress and qBittorrent queue status. Clicking an anime card opens its detail page, where stored anime metadata appears above a Sonarr-style episode table showing downloaded, queued, missing, and unaired episode states. Single-file anime movies with exactly one expected episode map their local file to episode 1 even when the filename has no episode number. Torrent queues and blocked history live under Activity; low-confidence candidate assignment lives under Anime > Manual Selection.

## Key Files

- `nyaarr/app_state.py`: Client-local JSON user anime library and dashboard stats.
- `nyaarr/torrent_finder.py`: nyaa.si RSS search, parsing, release grouping, and candidate selection.
- `nyaarr/qbittorrent_client.py`: qBittorrent Web API adapter for login, add torrent, list torrents, file listing, rename, and location updates.
- `nyaarr/templates/dashboard.html`: Shows real added anime, episode progress, and health notices.
- `nyaarr/templates/add_anime.html`: Posts selected metadata to `/anime`.

## nyaa.si RSS Use

The finder uses RSS, not HTML scraping:

```text
https://nyaa.si/?page=rss&q=<title>&c=1_2&f=0
```

Current category:

- `1_2`: Anime English-translated releases

Preserved fields include:

- Raw title
- Detail URL
- `.torrent` URL
- GUID
- Published date
- Seeders, leechers, downloads
- Infohash
- Category/category ID
- Size
- Trusted/remake flags

## Candidate Selection

The process looks for releases that explicitly appear to be:

- A batch/complete/season release
- A per-episode release with parseable episode numbering

Selection strategy:

1. Apply the anime's selected quality preference from Add Anime.
2. Ignore BluRay/BD/BDRip/BDMV/remux releases unless the anime was explicitly added with `BD`.
3. Score usable candidates with a confidence value from 0 to 100.
4. Add confidence for matching quality, matching a missing episode, batch suitability for an empty local library, healthy seed counts, known release group, matching the release group already used by local episode files, and prioritized subber matches.
5. Subtract confidence when the candidate has no reported seeders or no detected group. Preferred subbers are a boost and search-order preference, not a hard rejection of viable alternatives.
6. Sort candidates by confidence and then seeders.
7. Automatically push the best candidate to qBittorrent only when it meets `settings.torrent_confidence_threshold`, currently defaulting to `70`.
8. If no usable candidate exists or the best candidate is below threshold, set `torrent_manual_selection.required` on the anime instead of dispatching it. A search that returns no usable candidates is treated as manual intervention, not as a completed empty state.

Preferred subbers are stored as `settings.preferred_subbers`, a user-defined ordered list of release groups/subbers managed from Settings > Torrent preferences. The textarea accepts one release group per line or comma-separated values, such as `SubsPlease, Erai-raws, Judas`; spaces alone are not separators. Order matters: higher entries are searched first and keep priority when otherwise suitable releases are available. The Settings UI exposes these rules in a tooltip beside the field label. The list is normalized to always include `SubsPlease` as the first default. The finder tries preferred-subber title and episode RSS queries before generic queries, and the scorer treats membership as a confidence boost without penalizing other release groups when no preferred release is available.

When an anime falls back to a batch, Nyaarr still records the exact missing episode numbers. After qBittorrent downloads the torrent metadata, queue refresh reads `/api/v2/torrents/files` and applies file priorities: wanted episode files stay at normal priority and unrelated files are set to priority `0`. Non-media sidecars such as pictures and URL files, sample videos, already-present episodes, and media files with unparseable episode numbers are skipped rather than downloaded blindly. Supplied add-time torrent links use the same metadata pass to classify one media file as an individual episode or multiple parseable media files as a batch, then fill the queue wanted episode list from the parsed torrent file names and store per-episode selected file mappings. Dangerous executable, script, installer, and archive sidecars still flag the torrent instead of being silently skipped.



## Periodic Candidate Checks

The internal maintenance worker revisits every non-completed anime with missing episodes. Completed imports are skipped even if stale pending-search metadata exists. Manual-selection anime are the only missing-episode items exempt from automatic torrent refreshes until the user accepts or rejects a candidate. Active qBittorrent queues no longer block episode-finder refresh or dispatch for other missing episodes; dispatch deduplicates by hash/URL/title and skips episode numbers that are currently active in qBittorrent. Queue refresh preserves qBittorrent paused, stalled, and error states instead of flattening every active torrent to downloading. If an active per-episode torrent is saving to the root while the anime already has `local_path`, queue refresh calls qBittorrent `setLocation` to move it into that existing anime folder. It stores active qBittorrent progress as whole-number percent values for dashboard and Activity rendering. Activity still accepts older fractional values below `1`, but an active queue value of `1` is treated as `1%`, not complete; imported/completed records display as complete. `/activity/queued` polls `/activity/queued/data` every 5 seconds while the page is visible, so qBittorrent progress, ETA, and queue/history counts update without a full page reload. Queue refresh marks stored queued torrents as missing when qBittorrent no longer reports them, so those episodes can be searched again. Missing queue records are ignored for dispatch dedupe when qBittorrent does not report the torrent, allowing the same or replacement torrent to be sent again if qBittorrent lost the original item. If a missing queue has a known hash and qBittorrent later reports that hash again, queue refresh revives the existing record instead of duplicating the add. That revived record is marked as an unblocked retry for visibility, but it still has to pass the local subber consistency audit when existing episode files identify a dominant release group. If a queued, paused, stalled, flagged, completed, imported, or error queue maps to an episode that is already present in local episode files, queue refresh reconciles it to imported and Activity suppresses it from the queued view; this prevents qBittorrent `missingFiles` errors from making completed episodes look queued again. If existing local episode files identify a dominant release group, queue refresh also audits active and completed Nyaarr-managed qBittorrent items before import. A queued, completed, or imported-but-still-seeding torrent from a different detected release group is deleted from qBittorrent with files, recorded as rejected under blocked activity, and the anime is queued for a fresh search so Nyaarr can request the matching subber instead. If the wrong release had already been imported, only local episode files matching that rejected queue episode and release group are removed from the anime record and disk so the episode becomes wanted again. Due torrent searches are refreshed after `NYAARR_TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS`, defaulting to the periodic maintenance interval, so existing candidates do not stop future episode-aware searches. Searches store `torrent_search.checked_at` so Nyaarr can retry later without repeatedly hitting nyaa.si.

Rate-limit safeguards:

- Page renders do not perform external nyaa.si refreshes.
- A background tick refreshes at most `NYAARR_MAX_TORRENT_SEARCHES_PER_TICK` due torrent searches, defaulting to 2.
- External requests inside a tick are spaced by `NYAARR_EXTERNAL_REQUEST_SPACING_SECONDS`, defaulting to 2 seconds.
- Remaining stale searches are deferred to later ticks.

Across refresh, maintenance, manual selection, sidebar counts, and dispatch, Nyaarr treats only non-blocked, non-rejected torrent candidates as usable. Ignored-only candidate lists are normalized to empty and the anime is placed in the no-candidates manual-link state, where Manual Selection lists each missing episode with its own torrent/magnet assignment form. The no-candidates state does not permanently block background search; once the search interval expires, maintenance retries Nyaa, and any newly usable high-confidence candidates clear the manual hold and continue through automatic dispatch. When a refreshed candidate list has usable, non-blocked releases and satisfies the normal prerequisites and confidence threshold, the worker calls the same qBittorrent dispatch path used by Add Anime. Per-episode candidates from the chosen release group are queued together for all still-missing episodes, so an active episode 7 download does not prevent episodes 2-6 or 8-12 from being added. If confidence is still too low, the anime remains flagged for Manual Selection. Dispatch retries are throttled with `torrent_dispatch_attempted_at` and `NYAARR_TORRENT_DISPATCH_RETRY_SECONDS`.
## Manual Selection

Low-confidence anime are exposed under Anime > Manual Selection at `/anime/manual-selection`. The current dashboard remains Anime > Anime List. The Manual Selection page reconciles candidates against qBittorrent before rendering, hiding exact hash matches and already-present same-anime episode torrents. It then recomputes confidence for displayed candidates, shows the confidence reasons, and lets the user select a candidate manually.

Manual selection also accepts user-provided magnet links, Nyaa view/download links, and direct `.torrent` URLs through `/anime/manual-selection/link`; submitted links bypass the confidence threshold but still use the same qBittorrent paused safety gate, file selection, and import tracking. The Anime Detail episode table exposes the same link assignment flow for missing rows through `/anime/<library_id>/episodes/manual-link`, rendering the link textbox and Assign button inside the File column for missing episodes so no separate action column is needed. A user can queue a specific missing episode directly even when the anime is otherwise unmonitored. Manual link assignment immediately runs the qBittorrent queue refresh after dispatch, allowing the paused safety gate to inspect and resume the torrent right away when metadata is available and Add Paused is off. Manual selection posts accepted candidates to `/anime/manual-selection/select`. A manually selected candidate bypasses the confidence threshold and immediately goes through the same qBittorrent add path, paused safety inspection, batch file selection, and queue tracking used by automatic dispatch. If selecting one episode leaves other unqueued manual candidates for the same anime, Nyaarr keeps the anime visible in Manual Selection so the next episode can be confirmed without waiting for a later page reload or search tick. If all stored manual candidates are hidden because they are already known in qBittorrent or are no longer selectable, Nyaarr clears those stale candidate rows, expires `torrent_search.checked_at`, and lets the background search run again immediately. Rejected candidates post to `/anime/manual-selection/reject`; Nyaarr records the candidate in `ignored_torrents`, clears the manual-selection hold, immediately refreshes torrent candidates, and attempts dispatch if the refreshed search finds a suitable replacement.

If every visible candidate for an anime is already present in qBittorrent, Nyaarr clears the manual-selection hold and records a torrent-search notice instead of asking the user to confirm duplicates. Sidebar Manual Selection counts use the same visible-row reconciliation as the Manual Selection page, so stale low-confidence holds are cleared before badge counts are returned. The shared sidebar shows a yellow Manual Selection indicator. When the Anime dropdown is closed, the yellow count appears on Anime beside the anime count; when opened, it appears beside Manual Selection. Zero-value indicators are hidden.

## Torrent Safety Gate

Nyaarr currently treats nyaa.si downloads as anime-video-only. Every selected torrent is added to qBittorrent paused first without a qBittorrent rename override, preserving the original torrent name while Nyaarr tracks the eventual normalized import folder separately. Queue refresh reads the torrent's file list through qBittorrent before allowing the download to continue. Once a torrent passes safety inspection, Nyaarr retries resume on later refreshes if qBittorrent still reports the item paused and the user did not explicitly choose Add Paused.
On application startup, the maintenance worker immediately performs a download-client status pass before the normal periodic delay. Legacy tracked torrents that are paused but missing safety metadata are sent through the same qBittorrent file inspection gate; safe torrents are resumed unless the user chose Add Paused.

Allowed files are limited to known video container extensions in `MEDIA_EXTENSIONS`. Any other extension, including common executable, script, installer, archive, image, subtitle, or text files, flags the whole torrent as compromised. If one file in a batch is flagged, the entire torrent is held.

Operationally, test pushes should add the torrent paused first, wait until qBittorrent exposes file metadata, apply `_inspect_torrent_safety()`, and only then start or resume the torrent. This keeps ad hoc API tests aligned with the same safety behavior as normal Add Anime dispatch.

Flagged torrent rows are no longer shown on the Anime List dashboard. Active and completed torrent state belongs under Activity, rejected flagged torrents appear under Activity > Blocked, and low-confidence candidate assignment belongs under Anime > Manual Selection. Activity > Queued includes currently missing episodes as wanted rows when no torrent is selected yet. It suppresses wanted rows for episodes already visible in qBittorrent, even if the older Nyaarr queue record was marked missing, so the queue page does not label active external/client torrents as unresolved.

Users can still resolve flagged torrents through the existing allow/reject routes when a dedicated review surface links to them; rejecting a torrent deletes it from qBittorrent, stores its infohash/detail/title key in `ignored_torrents`, refreshes candidates, and attempts to dispatch the next safe candidate.

Ignored torrents are skipped during future candidate selection so a rejected compromised torrent is not retried for the same or later search pass. Activity > Blocked exposes an Unblock action that removes the stored ignore key and allows that candidate to appear in future searches again.

Release group detection prefers leading bracket syntax such as `[SubsPlease]`, and also recognizes conservative TV/scene-style suffix groups when release metadata precedes the suffix, such as `x265-SUBBER` or `H 264-VARYG`.

Parser rule:

- Episode patterns such as `S02E10`, versioned episode names such as `S01E01v2`, dash-number names such as `- 01.mkv`, and season-shorthand names such as `S2 - 01` are classified before generic season wording so a single episode with an alternate title like `Season 2` is not mistaken for a full batch, and local season files are not miscounted as only the season number.
- Selected season is enforced before candidate selection. Season 1 accepts releases with no season marker or explicit season 1 markers, and rejects `S02`, `Season 2`, `S03`, `Season 3`, and equivalent roman/ordinal markers. Later seasons require an explicit matching season marker. Ordinal release titles such as `4th Season` are treated as explicit season markers.

## Current Limitations

- Library state is client-local JSON and has no multi-user isolation or locking yet.
- qBittorrent dispatch uses `.torrent` URLs from Nyaa RSS metadata and preserves the torrent client name/content name. Direct magnet extraction is not implemented yet.
- Completed download import is conservative. It imports only when qBittorrent exposes a local `content_path` or target folder path that Nyaarr can access from its runtime, and only media files that are not samples and match the queue wanted episode numbers are moved into the anime folder. If the anime already has `local_path`, import targets that folder instead of deriving a new folder from the release or AniList title. For completed top-level torrent folders without an existing local folder, Nyaarr asks qBittorrent to rename the folder to the AniList title, then records that normalized folder as `local_path`; this keeps Jellyfin-facing folders stable even when the torrent root name contains release-group or quality text. Rejected completed files are stored on the queue as `rejected_import_files`, and unmatched completed torrents remain `completed` with `import_status=blocked` instead of being marked imported.
- Selective batch downloading depends on qBittorrent metadata becoming available and on episode numbers being parseable from file names.
- The safety gate is intentionally strict and flags all non-video files. That includes legitimate extras such as subtitles or checksum files until Nyaarr has a richer per-file allow policy.
- qBittorrent `v5.1.4` may require `/api/v2/torrents/start`; Nyaarr falls back to `/start` when `/resume` returns HTTP `404`.
- Title matching derives a candidate series identity before episode/quality tokens. One-word titles such as `Monster` must match the release series title exactly, so similarly named anime like `Monster Musume` or `Pocket Monsters` are not accepted by token containment. The finder still tries stored original and metadata search titles before giving up, so alternate release names can match without broadening simple-title searches.
- Episode parsing is heuristic and needs fixtures before production use.
- Queue status refresh runs in background maintenance. Activity pages render stored queue state immediately and avoid live qBittorrent refreshes during page load; qBittorrent status updates arrive on the next maintenance tick.

## Episode Search Planning

Before selecting a per-episode release, `find_torrents_for_anime()` builds the missing episode set from parsed local episode filenames when available, falling back to local progress and airing metadata, then runs episode-specific RSS queries for every planned missing number using the title variant that actually matched Nyaa results. This prevents a generic title search from selecting only the latest visible episode when earlier episodes have fallen off the first RSS response, and allows shows like Re:Zero season 4 to fall back from the English title to the release title used on Nyaa. If existing local files already establish a dominant release group/subber, the finder keeps checking AniList title variants when an earlier title only finds other groups; this lets a show with English-title releases on Nyaa still resolve romanized-title releases from the already-used subber, such as SubsPlease.

Torrent confidence now independently checks the parsed torrent series title against the selected anime title, Romaji/original title, stored aliases, metadata search titles, and provider title fields. Matches through aliases, Romaji, or metadata titles receive a small confidence boost and an explicit reason, while a longer different-series title, such as `Monster Hunter Stories Ride On` for AniList `Monster`, is penalized below the automatic dispatch threshold and should require manual review instead of being queued as a same-title match.

Per-episode selection is group-consistent. A release group/subber that matches the dominant release group parsed from existing local episode filenames is preferred when available; if no local files exist yet, queued supplied torrents with a detected release group can provide the same preference signal, keeping encodes/subtitle style consistent across a series. Otherwise, a release group/subber that covers every currently planned missing episode is preferred; when older missing episodes are unavailable from RSS, Nyaarr still returns the best same-group subset so available gaps can be queued. Once a group is chosen, candidate selection keeps the best seeded release per episode before applying the candidate cap, so duplicate uploads for early episodes cannot crowd out later missing episodes. If a batch exists for an empty local library, the batch path is still preferred. If only stale per-episode candidates remain after an episode has downloaded, dispatch skips candidates whose episode number is no longer missing.

When individual episode torrents from the chosen subber are stalled long enough or have too few seeds, the finder performs explicit batch/complete RSS searches and may select a batch from that same subber as a fallback. The fallback is marked with the exact missing episode numbers that caused it, then goes through the normal confidence threshold, title matching, quality matching, paused safety gate, and selective batch file-priority pass. This lets cases like a stalled Hunter x Hunter episode use a same-subber batch for only the needed files without switching release groups or downloading extras. The defaults are `NYAARR_STALLED_TORRENT_BATCH_FALLBACK_SECONDS=21600` and `NYAARR_LOW_SEED_BATCH_FALLBACK_SEEDERS=3`.

When a batch torrent is queued for missing episodes that already have active individual episode torrents, Nyaarr treats the batch as the replacement plan. The qBittorrent torrents for those covered individual episodes are deleted with files and the queue records are marked `superseded`, while unrelated episode queues remain active. This cleanup runs both immediately after dispatching a batch and during queue refresh so older mixed states self-repair. Selected batch files are staged into the existing anime folder during import; if a same-named destination file is already present from an earlier individual torrent, the batch-selected file replaces it so the anime folder remains the canonical location. Later refreshes also scan the anime folder for already-staged selected batch files, making repeated queue refreshes idempotent after repair or partial import.

Episode-specific searches still use one RSS query per planned missing episode when needed, but they now run through a bounded worker pool (`NYAARR_NYAA_RSS_SEARCH_WORKERS`, default `8`) with a shorter configurable timeout (`NYAARR_NYAA_HTTP_TIMEOUT_SECONDS`, default `8`). Results are cached in memory for `NYAARR_NYAA_RSS_CACHE_TTL_SECONDS` seconds, default `300`, so repeated identical RSS lookups during nearby refreshes return immediately. For large backlogs (`NYAARR_LARGE_BACKLOG_BATCH_SEARCH_THRESHOLD`, default `6` missing episodes), Nyaarr tries batch/complete RSS queries before per-episode fan-out and skips episode-specific searches when a compatible batch candidate is found.


## Release Group Priority

Bracket-prefix release groups are preferred before scene-style suffix groups globally. For example, `[SubsPlease] Title - 01 [1080p]` ranks ahead of `Title S01E01 1080p WEB-DL x265-SomeGroup.mkv`, even when the suffix release has more seeders or matches a configured preferred subber. Nyaarr still preserves the raw torrent title and stores the parsed `release_group`; RSS-ingested releases also carry `release_group_source` as `prefix`, `suffix`, or `unknown`.
