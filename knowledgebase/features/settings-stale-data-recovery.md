# Settings stale-data recovery

Settings includes **Recovery → Hard reset stale app data** for installations that retain stale searches, issues, job history, or provider caches after an update.

The user must type `RESET` and accept a browser confirmation. Nyaarr first creates a consistent SQLite backup under `data/user/backups/`, then clears rebuildable search/automation state, stale issue records, inactive durable jobs, resolved metadata caches, offline metadata cache files, and in-memory Nyaa/torrent metadata caches. It queues startup, local storage, qBittorrent, root-folder, Nyaa, AniList, and offline metadata reconciliation.

The operation deliberately preserves:

- superadmin account and application settings;
- anime library identity and monitoring preferences;
- root-folder configuration and confirmed episode file paths;
- Jellyfin NFO files and media payloads;
- download queue mappings and qBittorrent torrents;
- audit records and existing event history.

The reset refuses to start while local reconciliation holds the maintenance lock. A failed backup stops the reset. Backups are not automatically deleted; retention management is a future improvement.

Important code: `hard_reset_stale_application_state` in `nyaarr/app_state.py`, the `/settings/recovery/hard-reset` route, `SQLiteStateRepository.backup`, and the Settings recovery panel.
