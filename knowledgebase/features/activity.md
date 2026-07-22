# Activity

The Activity page shows Nyaarr download queue records grouped into queued, history, and blocked views.

## What Changed

- Activity queue refresh now tolerates qBittorrent status-check failures after the client is created.
- If qBittorrent is configured but unreachable, queued rows remain visible and each queue message is updated with the status-check failure instead of returning a 500 from `/activity/queued/data`.
- Initial page renders now use real models and sidebar counts instead of loading placeholders, reducing navigation and page-content flicker.
- Queued Activity polling skips unchanged payloads and updates existing table rows in place when row identity is stable.
- Activity page renders and `/activity/queued/data` now use stored queue state only; live qBittorrent reconciliation runs in background maintenance so page loads do not block on the download client.
- Active qBittorrent queue state is reconciled by a dedicated background job every 5 seconds by default, matching the queued-page polling cadence. Configure this independently with `NYAARR_DOWNLOAD_QUEUE_REFRESH_INTERVAL_SECONDS`; broader filesystem, Nyaa, and metadata maintenance remains on its existing interval.
- Queue reconciliation also repairs a missing or invalid anime `local_path` by conservatively matching exactly one media-containing folder under the configured root against the anime title or original title. Once attached, episode files, card completion, episode rows, and locally satisfied queue records are updated in the same pass.
- Saving an anime as unmonitored clears its active queued/downloading/paused/stalled/error/pending/flagged queue records and manual torrent selection state while preserving completed/imported history. Activity Queued also skips unmonitored anime so wanted placeholders do not reappear. The unmonitored preference is sticky across add/update/root-scan refreshes; background torrent search and automatic dispatch stay paused until the user explicitly re-enables Monitored.

## Important Files

- `nyaarr/app_state.py`: `activity_model()` builds queued/history/blocked rows from stored state; `_refresh_download_queue()` handles qBittorrent outage cases from background maintenance.
- `nyaarr/templates/activity.html`: queued activity uses `/activity/queued/data` for periodic refresh.

## Current Limitations

- When qBittorrent is unreachable, Nyaarr cannot update live progress, ETA, or completion/import status. It preserves the last known queued status until qBittorrent can be reached again.
