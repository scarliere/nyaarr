# AniList Reconciliation and Jellyfin NFO Files

## What Changed

AniList is now treated as the final metadata source of truth for identified anime. Add Anime and root-folder import may still use anime-offline-database, Kitsu, or TMDB fallback metadata to bootstrap a usable library item when AniList is unavailable or missing useful poster data, but that fallback state is marked as pending final AniList reconciliation.

When a library item is resolved from AniList, either automatically or through a manual AniList ID override, Nyaarr writes a Jellyfin-compatible `.nfo` file containing the AniList provider ID.

## Why It Exists

Fallback providers are useful for getting a folder into the library with a title, poster, and episode count, but they should not become the long-term identity for anime. Jellyfin also needs a durable local metadata hint so the same AniList identity survives rescans and folder moves.

## Important Files

- `nyaarr/app_state.py`: tracks `anilist_reconciliation_status`, retries pending final AniList reconciliation, preserves fallback posters when AniList has no poster, and writes Jellyfin NFO files.
- `tests/test_app_state_torrent_refresh.py`: covers fallback-provider pending state, AniList retry eligibility, fallback poster preservation, root import NFO creation, refresh NFO creation, and manual AniList ID NFO creation.

## Behavior

- AniList matches with an AniList provider ID mark the anime as `anilist_reconciliation_status = "reconciled"`.
- Non-AniList metadata matches mark the anime as `anilist_reconciliation_status = "pending"` and clear `anilist_metadata_checked_at` so the maintenance worker can attempt final AniList reconciliation without waiting for the normal stale interval.
- If AniList later resolves the anime but does not provide a poster, Nyaarr keeps the existing fallback poster and poster source.
- NFO sync runs when writing the user database, after root-folder imports, after completed torrent imports, after manual metadata verification, after manual AniList ID overrides, and during periodic maintenance.
- Folder-backed anime write `tvshow.nfo`; file-backed single items write a sibling `.nfo` next to the media file.

- Root-folder scans read those NFO files before filename-based matching. An AniList ID receives an exact lookup, while temporary provider failures retain the NFO identity for later reconciliation.
- NFO identities do not bypass folder-integrity checks: an incompatible local/provider episode count is sent to manual verification as a possible mixed-anime folder.

## Current Limitations

- NFO files are written only when `local_path` exists on disk. An added anime without a downloaded/imported folder gets its NFO after a folder or file path exists.
- If AniList is unavailable, fallback metadata remains usable but marked pending until a later maintenance pass can reconcile it.