# Airing Schedule Refresh

Nyaarr stores provider airing metadata on each anime record: `status`, `air_date`, `next_airing_at`, `airing_episode`, `airing_source`, and `airing_schedule_checked_at`.

The periodic maintenance worker refreshes airing metadata every minute by default through `NYAARR_AIRING_REFRESH_MAX_AGE_SECONDS=60`. Each tick can refresh up to `NYAARR_MAX_AIRING_REFRESHES_PER_TICK`, defaulting to `100`, after the normal queue and torrent maintenance pass.

When a provider reports that a show has no next airing episode after the finale, Nyaarr now clears stale `next_airing_at`, `airing_episode`, and `airing_source` values. This prevents completed shows from remaining on the calendar because of an old next-airing value. Provider status still controls the airing tag: finished/completed/ended metadata becomes `Completed` even if the library is still missing local episode files.

Library completion remains file-based: an anime becomes `library_state = Completed` only when the provider status is finished and the configured root folder has all expected episode files.