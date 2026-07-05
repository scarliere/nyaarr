# Unmonitored Title Guards

Nyaarr stores title-level pause markers when a user unmonitors an anime from the detail preferences form. Each marker records normalized title identity, provider IDs, the source library ID, and a timestamp. Cold records use the shared JSONL `action`, `payload`, and `recorded_at` schema.

The system uses hot and cold storage:

- Hot storage lives in `unmonitored_titles` inside `data/user/anime-library.json` and is capped by `NYAARR_MAX_UNMONITORED_TITLE_ENTRIES` for fast in-process checks.
- Cold storage lives in append-only JSONL at `data/user/cold/unmonitored-titles.jsonl`, configurable with `NYAARR_UNMONITORED_TITLES_COLD_STORAGE_PATH`.
- When hot storage exceeds the cap, older pause markers are archived to cold storage instead of being discarded.
- When a title is explicitly monitored again, Nyaarr writes an `unpause` event so older cold `pause` records no longer resurrect the guard.

This exists so root-folder scans and other import refreshes do not recreate a previously paused title as monitored under a new `library_id`. Imports first check hot markers and existing paused library items, then scan cold storage by provider ID or normalized title/original/alias. A match forces the candidate to `monitored = false`, clears queued/candidate torrent work, and refreshes the library state to `Paused`.

Important files:

- `nyaarr/app_state.py`: preference save, root-folder candidate storage, hot/cold pause matching, and archive movement.
- `tests/test_app_state_torrent_refresh.py`: regression coverage for root-scan recreation, cold-storage lookup, overflow archival, and explicit remonitor cleanup.

Current limitations:

- Cold lookup scans the JSONL file linearly. This is acceptable for thousands of anime pause events, but a larger multi-user deployment should add an indexed sidecar or partition cold storage by provider/title key.
- Title-only matching is intentionally broad for older database entries without provider IDs. Two genuinely different titles with the same normalized name may share the pause guard until one is explicitly monitored again.