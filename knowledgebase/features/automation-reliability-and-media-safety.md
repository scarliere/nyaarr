# Automation Reliability and Media Safety

## What changed

Nyaarr now treats an added, monitored anime as an automation request that remains active until its wanted episodes are imported or a persistent issue needs user input.

- Manual release selection locks the confirmed release group and immediately searches and dispatches matching releases for remaining episodes.
- Empty/blocked searches retry automatically. Manual selection is exposed only after three exhaustive cycles or 24 hours, and an issue record provides the recovery action.
- Maintenance lock contention returns to the durable retry queue instead of being marked completed.
- qBittorrent activity in the configured Nyaarr category is limited to five active downloads. Torrents continuously below 100 KiB/s after grace are paused and rotated with bounded cooldowns. User/safety-paused, completed, and seeding torrents are excluded.
- Completed files use hardlink-first atomic staging, an 8 MiB copy buffer, fsync, and source/destination fingerprints. A different existing destination becomes a conflict instead of a false successful import. Torrent-owned source layouts are never deleted or moved.
- AniList NFO output is parsed before publication, fsynced, atomically replaced, and reports `nfo_status`/`nfo_anilist_id`. The Jellyfin contract remains `tvshow.nfo` (or sibling NFO for a root-level file) with the AniList unique ID; existing release filenames are preserved.
- Significant existing application events are also appended to SQLite `audit_events`. The compatibility UI event list remains bounded.
- In-memory compatibility state history is capped at eight full snapshots to avoid revision-history RAM spikes.

## Important files

- `nyaarr/torrent_scheduler.py`: capacity and slow-torrent rotation policy.
- `nyaarr/app_state.py`: automation escalation, confirmed-subber continuation, queue reconciliation, atomic imports, NFO readiness, audit connection.
- `nyaarr/maintenance.py`: contention-aware durable retry behavior.
- `nyaarr/qbittorrent_client.py`: pause/stop compatibility adapter.
- `nyaarr/audit.py`: append-only SQLite audit sink.
- `nyaarr/persistence.py`: bounded compatibility revision history.

## Current limitations

Nyaarr preserves torrent payloads and existing Jellyfin filenames; it does not rename or delete qBittorrent-owned content. Path conflicts and inaccessible completed-download paths require user review rather than destructive guessing. Issue records are visible in the System > Issues inbox and resolve when user intervention successfully resumes automation. Audit archival/export remains future work.
