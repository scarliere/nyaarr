# Resource Management Controls

Nyaarr now includes guardrails for the highest-risk local resource flows: duplicate app processes, retained JSON state, Nyaa RSS fan-out, and root-folder scans.

## What changed

- `main.py` acquires a single-instance lock at `data/user/nyaarr.lock` before creating the Flask app. Set `NYAARR_DISABLE_INSTANCE_LOCK=1` only for intentional parallel development runs.
- `nyaarr/app_state.py` prunes retained state before database writes:
  - `ignored_torrents` defaults to the latest 500 entries.
  - per-anime historical `download_queues` defaults to 75 inactive entries while keeping active queues.
  - metadata candidates, flagged file lists, selected batch file lists, rejected import file lists, and resolved metadata cache entries are capped.
- `nyaarr/torrent_finder.py` clamps RSS workers to 16, caps cached RSS query entries, evicts expired cache rows, and caps episode-specific RSS fan-out for large backlogs.
- Root-folder background scans now import each top-level candidate as it is found instead of first retaining a full candidate list for the entire scan.
- User database writes now skip replacing the JSON file when the serialized content is unchanged.

## Configuration

- `NYAARR_INSTANCE_LOCK_PATH`: override the lock-file path.
- `NYAARR_DISABLE_INSTANCE_LOCK=1`: disable the process lock.
- `NYAARR_MAX_IGNORED_TORRENTS`: default `500`.
- `NYAARR_MAX_QUEUE_HISTORY_PER_ANIME`: default `75`.
- `NYAARR_MAX_METADATA_CANDIDATES_PER_ANIME`: default `10`.
- `NYAARR_MAX_FLAGGED_FILES_PER_QUEUE`: default `25`.
- `NYAARR_MAX_SELECTED_FILES_PER_QUEUE`: default `100`.
- `NYAARR_MAX_RESOLVED_METADATA_CACHE_ENTRIES`: default `2000`.
- `NYAARR_NYAA_RSS_CACHE_MAX_ENTRIES`: default `256`.
- `NYAARR_NYAA_MAX_EPISODE_SEARCH_QUERIES`: default `72`.
- `NYAARR_NYAA_RSS_SEARCH_WORKERS`: default `8`, clamped to `16`.

## Current limitations

The app still uses a whole-file JSON database, so each request that reads state still pays a cost proportional to retained library size. These controls reduce unbounded growth, but a larger future migration should move anime, queue, event, and ignored-torrent records into an indexed store.

Root-folder scans still sort top-level entries and collect media files within each anime folder so progress and deterministic imports remain stable. Very large single anime folders can still be expensive to scan.
