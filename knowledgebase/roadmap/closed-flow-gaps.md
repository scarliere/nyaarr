# Closed Flow Gaps

## 2026-07-03 Preferred Subbers and User-Control Gaps

These gaps were found while investigating why a newly added anime could download from a non-preferred release group even though the system appeared to prefer SubsPlease.

### Gaps Found

- Preferred subbers had backend scoring behavior but no Settings UI, so a normal user could not see or edit `settings.preferred_subbers`.
- New client databases and old databases could leave `preferred_subbers` empty, so the torrent finder had no default SubsPlease preference to act on.
- Torrent search used preferred subbers only as a confidence signal after candidates were found. Add Anime and root-folder refresh did not try preferred-subber RSS queries before generic Nyaa title queries.
- Preferred-subber scoring penalized every non-preferred group when a preferred list existed. That made the new default too strict when no preferred release existed.
- Anime detail exposed AniList ID editing but not core controls a user expects after adding/importing anime: quality preference, season hint, monitoring, and remove-from-library.
- Activity > Blocked showed rejected candidates but had no unblock path, making a bad rejection hard to recover from in the UI.
- Metadata Review depended on stored candidate rows and had no direct AniList ID entry path for ambiguous root-folder imports.
- qBittorrent Settings still displayed Recent Priority and Older Priority fields even though they were not active behavior in the current qBittorrent integration.

### Fixes Made

- `settings.preferred_subbers` now normalizes through `DEFAULT_PREFERRED_SUBBERS = ["SubsPlease"]`, so SubsPlease is always present by default and remains first after saves.
- Settings now includes a Torrent preferences panel for preferred subbers and automatic confidence threshold.
- `_refresh_torrent_search()` passes the normalized preferred list into `find_torrents_for_anime()` for Add Anime background work, root-folder imports, and periodic refreshes.
- `find_torrents_for_anime()` accepts preferred subbers and tries preferred-subber title and episode RSS queries before generic queries when the list is non-empty.
- Candidate selection prefers configured subbers when releases are otherwise available, while confidence now boosts preferred groups without rejecting viable fallback groups solely for not being preferred.
- Anime Detail now exposes quality, season number, monitored toggle, and remove-from-library actions.
- Activity > Blocked now exposes Unblock for stored ignored torrent keys.
- Metadata Review now accepts a direct AniList ID per pending root-folder import.
- The qBittorrent dialog no longer shows inactive Recent Priority or Older Priority fields.

### Important Files

- `nyaarr/app_state.py`: preferred-subber defaults, settings save, refresh propagation, anime preferences/delete, blocked unblock, confidence scoring.
- `nyaarr/torrent_finder.py`: preferred-subber-first RSS query planning and preferred group selection.
- `nyaarr/__init__.py`: routes for torrent preferences, anime preferences/delete, blocked unblock, and metadata AniList ID.
- `nyaarr/templates/settings.html`: Torrent preferences UI and qBittorrent field cleanup.
- `nyaarr/templates/anime_detail.html`: anime preference/delete controls.
- `nyaarr/templates/activity.html`: blocked torrent unblock controls.
- `nyaarr/templates/metadata_verification.html`: direct AniList ID form.
- `tests/test_torrent_finder.py` and `tests/test_app_state_torrent_refresh.py`: regression coverage.

### Current Limitations

- Preferred subbers are still release-group text matches from Nyaa titles/RSS metadata. They do not verify subtitle language or encode details inside torrent files.
- Preferred subbers are a search-order preference and confidence boost, not an exclusive allow-list. If no preferred release is available, Nyaarr can still select another safe, high-confidence candidate.
## 2026-07-03 AniList Reconciliation and Jellyfin NFO Gaps

These gaps were found while tightening add/import flows after the preferred-subber investigation.

### Gaps Found

- Add Anime and root-folder import could settle on fallback provider metadata without marking that AniList still needed to become the final identity.
- AniList poster reconciliation behaved like an initial provider choice instead of a final reconciliation pass, so fallback posters and final AniList IDs were not clearly separated.
- Properly identified anime did not write a Jellyfin-readable NFO file containing the AniList ID.

### Fixes Made

- Fallback provider matches now mark `anilist_reconciliation_status = "pending"` and clear `anilist_metadata_checked_at` so the maintenance worker can retry AniList reconciliation immediately instead of waiting for the stale interval.
- Successful AniList reconciliation marks the item `reconciled`, preserves any existing fallback poster when AniList has no poster, refreshes library state, and records the metadata update.
- Identified anime with a real local folder write `tvshow.nfo` with `<uniqueid type="anilist" default="true">...`; file-backed items write a sibling `.nfo`.

### Important Files

- `nyaarr/app_state.py`: AniList reconciliation flags, refresh handling, fallback poster preservation, and Jellyfin NFO writer.
- `knowledgebase/features/anilist-reconciliation-and-nfo.md`: focused implementation note.
- `tests/test_app_state_torrent_refresh.py`: regression coverage for pending fallback state, AniList retry eligibility, poster preservation, and NFO creation.

### Current Limitations

- NFO writing requires `local_path` to exist on disk. Add Anime entries without a local folder get their NFO after download/import creates a folder or file path.
