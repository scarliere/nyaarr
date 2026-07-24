# Long-series queue and subber controls

## What changed

- Activity pages build only the requested section. Sidebar counts no longer contact qBittorrent or mutate manual-selection state, which keeps the Queued shell fast.
- qBittorrent `stopped*` states are treated like paused states. Safe Nyaarr-owned torrents are resumed with bounded retry backoff; untracked stopped torrents are left untouched and create a review issue.
- Finished anime with more than 30 expected episodes use batch-first search and one aggregate wanted row. Ongoing long anime continue to search and select individual episodes.
- Queued rows have their selection checkbox at the left. The page-level **Remove Subber** action blocks each selected release group only for the selected anime, removes matching active torrents and payloads, retries failed cleanup, and exposes the block under Activity > Blocked for reversal.
- AniList-resolved anime use the AniList title for new library folders. Imported media is flattened into that folder. Maintenance can non-destructively stage existing media into a canonical sibling folder after collision checks; original files remain available for seeding/recovery.

## Important code

- `nyaarr/app_state.py`: queue models/actions, qBittorrent recovery, import and storage reconciliation.
- `nyaarr/torrent_finder.py`: long-series search and selection policy.
- `nyaarr/torrent_scheduler.py`: normalized active/stopped state handling.
- `nyaarr/templates/activity.html`: bulk queue selection and blocked-subber controls.

## Limitations

- The long-series cutoff defaults to 30 episodes and can be changed with `NYAARR_LONG_SERIES_EPISODE_THRESHOLD`.
- Existing folder reconciliation preserves the original tree and only switches the library path after every media file is safely staged. Filename collisions with different content require manual review.
- An untracked stopped torrent is never resumed or deleted automatically because Nyaarr cannot prove ownership.
