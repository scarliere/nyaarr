# Settings Root Folder

The Settings page owns the local anime root folder.

## Routes

- `GET /settings`: Shows root folder status and configuration.
- `POST /settings/root-folder`: Saves the selected root folder and queues a background import scan.
- `POST /settings/root-folder/delete`: Removes the saved root folder path.
- `GET /settings/status`: Returns the current missing required settings summary for sidebar refreshes.

## Behavior

- If no root folder is selected, the root folder section shows a yellow `!` warning explaining that a root folder lets Nyaarr read existing anime and save downloads.
- The user enters the local anime folder path and clicks `Save and scan`.
- When a root folder is saved, a `Delete` button appears beside `Save and scan`. It clears `settings.root_folder` and removes anime records imported from root-folder scans from the anime list.
- The path must exist and be a directory.
- The saved path is stored in `settings.root_folder` inside the client-local JSON database.
- Downloads target this root folder when qBittorrent is configured and a selected Nyaa candidate passes the dispatch criteria.
- The shared sidebar counts missing required settings at render time. It shows a yellow count badge on Settings when the root folder path or download client config is absent.
- Each incomplete Settings subsection shows its own yellow `!` explanation for the missing required input.
- The base layout polls `/settings/status` every 10 minutes to refresh the Settings badge without a full page reload.
- Anime added through Add Anime remain in the list even when no root folder is selected. If they still need episode downloads, their dashboard state is `Undownloadable` with an orange hover badge until a root folder is configured.

## Import Scan

The scan imports:

- Immediate child folders that contain media files.
- Media files placed directly inside the root folder.

Imported records use:

- `source`: `Root Folder Scan + AniList` when the folder/file name has a confident AniList match.
- `source`: `Root Folder Scan` when no confident AniList match is found.
- `local_path`: resolved path to the folder or file
- `episode_files`: resolved media file paths
- `media_info`: sampled video metadata from the first readable local media file.
- `media_tags`: media quality tags such as `720p`, `1080p`, or `2160p`.
- `torrent_search.strategy`: `Imported from root folder scan`
- `manual_verification_required`: `true` for unresolved or ambiguous metadata matches.
- `metadata_candidates`: up to three AniList candidates for manual review, including provider IDs when available so the selected candidate can be refreshed and applied later.

The scanner is idempotent by root path ID. Re-scanning updates existing scanned entries instead of duplicating them.

Root-folder imports are stored with `library_id` values prefixed by `root-folder:`. Root-folder deletion first seeds verified root-folder metadata into `data/cache/resolved-anime-metadata.json`, then removes entries with that prefix and leaves anime added through the Add Anime flow intact. The resolved metadata cache is not deleted, so reimporting the same root can match cached records before calling metadata providers.

After each root-folder import is identified, Nyaarr refreshes Nyaa RSS candidates and can dispatch a suitable non-BD torrent to qBittorrent when episodes are missing and download-client settings are configured.

## Completion State

After metadata resolution, Nyaarr compares local media files against the resolved anime episode count.

An anime is marked `Completed` when:

- Metadata status is finished/completed/ended.
- The resolved episode count is known.
- The number of detected local media files is greater than or equal to the expected episode count.

Otherwise it remains `Monitored` when monitoring is enabled, or `Paused` when monitoring is disabled. Dashboard cards show the state badge and the local/expected episode count when the expected count is known.

## Media Quality Tags

Root-folder scans sample one media file per imported anime folder and use `ffprobe` to read the first video stream dimensions.

Expected command shape:

```text
ffprobe -v error -select_streams v:0 -show_entries stream=width,height -of json <file>
```

Nyaarr maps the detected dimensions to a quality tag such as `480p`, `720p`, `1080p`, `1440p`, or `2160p`, stores it in `quality_tag`, and adds it to `media_tags` for dashboard display.

Once an anime has a stored `quality_tag` plus resolved video `width` and `height`, normal scans reuse that cached media resolution and do not run `ffprobe` again for that anime. This keeps root-folder rescans cheap and avoids repeatedly touching large media files. A code-level forced refresh can still be run with `refresh_library_media_tags(force=True)` when the quality mapping logic changes or the user intentionally wants to re-sample files.

The stored `quality_tag` is treated as the canonical resolution. When it is applied, stale resolution tags such as an older `720p` value are removed from `media_tags` before the current tag is added.

Dashboard cards hide the generic `Any 1080p` quality profile whenever a resolved media quality tag exists, so users see the concrete detected resolution instead of both labels.

If `ffprobe` is missing in the current environment, media probing is skipped without failing the scan. Production should provide `ffprobe` on `PATH`, or set `NYAARR_FFPROBE_PATH`.

For local installs, run:

```text
python scripts/install_ffprobe.py
```

The installer downloads a Windows FFmpeg build and extracts the `bin` directory to `tools/ffmpeg/bin/`. Nyaarr resolves `ffprobe` in this order:

1. `NYAARR_FFPROBE_PATH`
2. `tools/ffmpeg/bin/ffprobe.exe`
3. `ffprobe` on `PATH`

## AniList Resolution

Each scanned title is searched against the metadata resolver during import. AniList is still the primary provider, and anime-offline-database is used as the first fallback when AniList is unavailable, rate-limited, or returns no usable match.

Before calling providers, Nyaarr checks the local resolved metadata cache at `data/cache/resolved-anime-metadata.json`. Confident provider matches are written back to that cache by cleaned search title, so unlinking the root folder and scanning it again can reuse previous resolutions without pinging AniList for the same anime. Root-folder deletion does not purge this cache.

Cache hits are validated against parsed year and season hints before reuse. This prevents a generic title cache entry from resolving a dated `S01` folder to a later season.

Before searching, Nyaarr removes common release/spec tokens from folder and file names so encoder details do not pollute metadata matching. Examples include resolution (`1080p`, `2160p`), source (`WEBRip`, `WEB-DL`, `BDRip`, `BluRay`), codecs (`x264`, `x265`, `HEVC`, `AV1`), audio (`AAC`, `DD+`, `DDP5.1`, `EAC3`, `FLAC`, `Opus`), language/subtitle markers (`Dual Audio`, `Multi-Subs`, `ENG SUB`), release revisions (`v2`, `REPACK`, `PROPER`), platform tags (`CR`, `AMZN`, `DSNP`, `HIDIVE`), CRC hashes, and leading release-group brackets.

Search variants include the stripped folder title, parenthesized aliases such as English names, and the stripped title with parenthesized text removed. This lets folders such as `Kage no Jitsuryokusha ni Naritakute! (The Eminence in Shadow)` search both the Romaji/Japanese title and the English title.

Year and season markers from release-style folder names are used as match clues, not as title text. For example, `2.5 Dimensional Seduction (2024) S01 ...` searches `2.5 Dimensional Seduction` while using `2024` and season `1` to prefer the first season over later/upcoming seasons that share the same English alias.

Resolution is accepted only when the best returned title/original-title match is strong and not too close to another candidate. Accepted matches enrich the local import with metadata title, year, status, provider episode count, season number, runtime, genres, studio, rating, synopsis, poster, and provider IDs while preserving the local path and detected episode files.

Root-folder metadata matching cross-checks detected local episode count against provider episode count whenever the provider or cache has an episode total. A cached/provider match is rejected when the local file count is greater than the matched anime's expected episodes. During import and database normalization, Nyaarr also rejects two entries with the same resolved display title unless their provider identity, expected episode count, and detected local episode count all match. Conflicting same-title imports keep their local folder name and are flagged for manual metadata verification.

If a re-scan hits a transient provider failure, Nyaarr does not downgrade an already verified import into manual verification. It updates local file paths and episode files while preserving the existing verified metadata.

Saving the root folder also seeds the cache from already verified library records before scanning. This protects existing metadata from provider outages and rate limits.

Uncertain matches remain in the library but are flagged in dashboard badges, the Health panel, and Anime > Metadata Review for manual verification. Selecting a candidate applies provider metadata, clears the manual verification flag, refreshes the local completion state, records a metadata event, and queues background torrent search when episodes are missing.

## Current Limitations

- Browser-native folder picking is not implemented; the local path is entered as text.
- Scanned imports use filesystem names when AniList cannot provide a confident match.
- Media quality detection requires `ffprobe`.
- The scan does not move, rename, or delete files.
- Root-folder scans queue missing-episode torrent searches for the background worker instead of running nyaa.si searches inline.

## Loading Behavior

Root folder scans do not run live torrent searches inline. Imported anime with no cached torrent data are marked as queued for background torrent search only when they still need episodes. Completed imports are not queued; their torrent search strategy is `No torrent search needed`. Dashboard cards and the Health panel suppress those internal queue/no-search placeholders so users only see actionable health warnings. The periodic maintenance worker refreshes pending imports under the global request caps.

Root folder metadata matching checks the resolved metadata cache first, then attempts live provider matching in the background scan before falling back to manual verification. When a scanned folder matches an anime that is already in the library, the scan updates that existing item with local files instead of creating a duplicate root-folder import. If a stale root-folder duplicate already exists for the same local folder, database normalization and the next scan remove that duplicate and merge the local files into the provider-backed item. Partial folders remain monitored, and missing episode searches use parsed episode numbers from local filenames when available so gaps such as episodes `1`, `2`, or `10` are queued instead of only tail episodes.
## Live Scan Progress

Saving the root folder from Settings uses a fetch-based form submission that returns as soon as the path is validated and the background scan is queued. The Settings page polls `/settings/root-folder/progress` while it remains open, and users can move to other pages without stopping the scan. The progress payload includes `active`, `phase`, `current`, `total`, `percent`, `message`, and the current import summary.

The progress bar starts immediately, reports milestones for validation, reading folders, checking top-level media, resolving metadata, importing records, and completion/failure. During top-level media checks the count is `checked item / total items`; during import the count is `imported anime / total anime`. If the user reloads or returns to Settings while a scan is active, the page resumes polling the existing scan.
