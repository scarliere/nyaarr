# Resource Management Controls

Nyaarr now includes guardrails for the highest-risk local resource flows: duplicate app processes, retained JSON state, Nyaa RSS fan-out, root-folder scans, and long-lived historical decisions.

## What changed

- `main.py` acquires a single-instance lock at `data/user/nyaarr.lock` before creating the Flask app. Set `NYAARR_DISABLE_INSTANCE_LOCK=1` only for intentional parallel development runs.
- `nyaarr/app_state.py` keeps hot JSON state bounded before database writes while archiving older durable records to append-only cold storage:
  - `ignored_torrents` defaults to the latest 500 hot entries; older ignore decisions move to cold storage and still participate in future torrent filtering.
  - `unmonitored_titles` defaults to the latest 500 hot entries; older pause markers move to cold storage and still protect against root-scan resurrection.
  - per-anime historical `download_queues` defaults to 75 inactive hot entries while keeping active queues; older inactive queues move to cold storage for audit/history.
  - metadata candidates, oversized flagged-file lists, selected batch file lists, rejected import file lists, and resolved metadata cache evictions are archived instead of silently discarded.
- `nyaarr/torrent_finder.py` clamps RSS workers to 16, caps cached RSS query entries, evicts expired cache rows, and caps episode-specific RSS fan-out for large backlogs. These remain true runtime cache/fan-out controls; cold storage would not improve correctness here.
- Root-folder background scans now import each top-level candidate as it is found instead of first retaining a full candidate list for the entire scan.
- User database writes now skip replacing the JSON file when the serialized content is unchanged.

## Cold Storage

Cold storage uses append-only JSONL files under `data/user/cold` by default. Each line has `action`, `payload`, and `recorded_at` fields. This keeps the main JSON database small while preserving older operational decisions and history.

Default files:

- `ignored-torrents.jsonl`
- `unmonitored-titles.jsonl`
- `download-queues.jsonl`
- `metadata-candidates.jsonl`
- `resolved-metadata-cache.jsonl`

Ignored torrent and unmonitored-title cold records are decision-active: Nyaarr reads them when filtering future torrents or preventing root-folder scans from re-monitoring paused titles. Queue, metadata-candidate, oversized file-list, and resolved-cache cold records are currently archive-only.

## Configuration

- `NYAARR_INSTANCE_LOCK_PATH`: override the lock-file path.
- `NYAARR_DISABLE_INSTANCE_LOCK=1`: disable the process lock.
- `NYAARR_COLD_STORAGE_DIR`: override the default cold-storage directory.
- `NYAARR_IGNORED_TORRENTS_COLD_STORAGE_PATH`: override ignored-torrent cold storage.
- `NYAARR_UNMONITORED_TITLES_COLD_STORAGE_PATH`: override unmonitored-title cold storage.
- `NYAARR_DOWNLOAD_QUEUES_COLD_STORAGE_PATH`: override queue-history cold storage.
- `NYAARR_METADATA_CANDIDATES_COLD_STORAGE_PATH`: override metadata-candidate cold storage.
- `NYAARR_RESOLVED_METADATA_COLD_STORAGE_PATH`: override resolved metadata cache cold storage.
- `NYAARR_MAX_IGNORED_TORRENTS`: default `500`.
- `NYAARR_MAX_UNMONITORED_TITLE_ENTRIES`: default `500`.
- `NYAARR_MAX_QUEUE_HISTORY_PER_ANIME`: default `75`.
- `NYAARR_MAX_METADATA_CANDIDATES_PER_ANIME`: default `10`.
- `NYAARR_MAX_FLAGGED_FILES_PER_QUEUE`: default `25`.
- `NYAARR_MAX_SELECTED_FILES_PER_QUEUE`: default `100`.
- `NYAARR_MAX_RESOLVED_METADATA_CACHE_ENTRIES`: default `2000`.
- `NYAARR_NYAA_RSS_CACHE_MAX_ENTRIES`: default `256`.
- `NYAARR_NYAA_MAX_EPISODE_SEARCH_QUERIES`: default `72`.
- `NYAARR_NYAA_RSS_SEARCH_WORKERS`: default `8`, clamped to `16`.

## Scale Recommendations

Append-only JSONL cold storage is a good local-app improvement because writes are cheap, the hot database stays small, and old user decisions are not lost. For thousands of anime on one machine, this is reasonable.

For industrial scale or multi-user deployments, move hot and cold state into an indexed store. Recommended path:

- SQLite first for this app: tables for anime, queue_events, ignored_torrents, unmonitored_titles, metadata_candidates, and provider_cache, with indexes on provider IDs, normalized title keys, torrent keys, and timestamps.
- Postgres when multiple workers/users are involved: partition historical queue/events tables by month and use background jobs for compaction.
- Add cold indexes before cold files get large: either SQLite sidecar indexes or JSONL partitioning by record type and date/provider hash.
- Keep true runtime caches in memory with TTL/LRU eviction. Do not cold-store Nyaa RSS response cache misses or search fan-out attempts unless they become audit requirements.

## Current limitations

The app still uses a whole-file JSON database, so each request that reads state still pays a cost proportional to retained hot library size. Cold storage reduces unbounded JSON growth, but decision-active cold lookups are currently linear JSONL scans. That is acceptable for thousands of records, but should become indexed before the data reaches hundreds of thousands of records.

Root-folder scans still sort top-level entries and collect media files within each anime folder so progress and deterministic imports remain stable. Very large single anime folders can still be expensive to scan.
