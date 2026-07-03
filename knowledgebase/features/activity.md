# Activity

The Activity page shows Nyaarr download queue records grouped into queued, history, and blocked views.

## What Changed

- Activity queue refresh now tolerates qBittorrent status-check failures after the client is created.
- If qBittorrent is configured but unreachable, queued rows remain visible and each queue message is updated with the status-check failure instead of returning a 500 from `/activity/queued/data`.
- Initial page renders now use real models and sidebar counts instead of loading placeholders, reducing navigation and page-content flicker.
- Queued Activity polling skips unchanged payloads and updates existing table rows in place when row identity is stable.
- Activity page renders and `/activity/queued/data` now use stored queue state only; live qBittorrent reconciliation runs in background maintenance so page loads do not block on the download client.
- Saving an anime as unmonitored clears its active queued/downloading/paused/stalled/error/pending/flagged queue records and manual torrent selection state while preserving completed/imported history. Activity Queued also skips unmonitored anime so wanted placeholders do not reappear.

## Important Files

- `nyaarr/app_state.py`: `activity_model()` builds queued/history/blocked rows from stored state; `_refresh_download_queue()` handles qBittorrent outage cases from background maintenance.
- `nyaarr/templates/activity.html`: queued activity uses `/activity/queued/data` for periodic refresh.

## Current Limitations

- When qBittorrent is unreachable, Nyaarr cannot update live progress, ETA, or completion/import status. It preserves the last known queued status until qBittorrent can be reached again.
