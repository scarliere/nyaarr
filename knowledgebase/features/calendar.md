# Calendar

The calendar shows exact and, where explicitly labeled, estimated episode air dates for saved anime.

## What Changed

- Added a `/calendar` Flask route with weekly and monthly views.
- Added a Calendar sidebar link that uses the same active navigation pattern as Anime and Settings.
- Added an Upcoming airings section so future scheduled episodes are visible even when they fall outside the selected week/month. Upcoming cards place the date at the top, with a larger poster column on the left and episode/source details to the right.
- Added automatic airing-state tags on saved anime cards: `Airing`, `Completed`, `Not Yet Aired`, or `Unknown`. Provider status values are normalized before tagging; for example Kitsu `Current` is treated as `Airing`.
- Extended normalized metadata with schedule fields:
  - `air_date`
  - `next_airing_at`
  - `airing_episode`
  - `airing_source`
- AniList snapshots request recent past and future `AiringSchedule` rows as well as `nextAiringEpisode`.
- Kitsu `startDate` and TMDB `first_air_date` can seed a date-only calendar entry when that date is today or in the future.
- The Add Anime form posts schedule fields into the local JSON library so calendar rendering does not require live provider access.
- Opening the calendar reads indexed SQLite schedule rows only; it never waits on AniList.
- Navigating to an uncached week, month, or historical year enqueues idempotent monthly schedule jobs for the library's AniList IDs. The fragment shows cached rows immediately and polls until the requested months are hydrated.

## Important Files

- `nyaarr/__init__.py`: `/calendar` route and Add Anime schedule-field persistence.
- `nyaarr/airing_repository.py`: indexed exact/estimated episode schedule and per-month coverage records.
- `nyaarr/app_state.py`: `refresh_library_anilist_state()` and `hydrate_calendar_airing_window()`.
- `nyaarr/app_state.py`: `calendar_model()` builds week/month grids from cached rows and enqueues missing windows.
- `nyaarr/app_state.py`: airing-state tag derivation from provider status and saved schedule fields.
- `nyaarr/metadata.py`: AniList next-airing metadata normalization plus date-only fallback schedules.
- `nyaarr/templates/calendar.html`: weekly/monthly calendar page.
- `nyaarr/static/css/app.css`: calendar layout, view switcher, and responsive behavior.

## Behavior

The calendar accepts:

- `view=week` or `view=month`
- `date=YYYY-MM-DD`

Examples:

```text
http://127.0.0.1:1269/calendar
http://127.0.0.1:1269/calendar?view=month&date=2026-06-23
```

Weekly view renders the Monday-Sunday week containing the selected date. Monthly view renders a full week-aligned month grid. Calendar entries are sorted by the configured display timezone and title. The Upcoming airings section lists the next saved future air dates across the whole library, independent of the current grid period.

Historical data is fetched only for a viewed period and in chunks of at most 50 AniList IDs. Pagination continues as durable background jobs, and month coverage is marked only after the final page succeeds. Returning to a covered period is a local indexed read.

## Current Limitations

- Full episode history requires an AniList ID. Kitsu and TMDB date-only metadata remains a compatibility fallback for a series start date.
- AniList can omit or later correct schedule rows. Exact provider data overwrites estimates; estimates cannot overwrite exact rows.
- Exact provider timestamps are stored as UTC but displayed and date-bucketed in the configured display timezone. Date-only fallback entries display `TBA`.

## Display Format

Displayed date labels use day month year order, for example 24 Jun 2026. Exact calendar times use `HH:MM <timezone>`, defaulting to `GMT+8` until changed in Settings. Machine values in URLs, form fields, and stored metadata remain ISO YYYY-MM-DD or UTC timestamps for parsing and interoperability.

## Airing Status Priority

Schedule refreshes now prefer an existing AniList provider ID before falling back to title search. This keeps saved anime aligned with AniList status changes such as `Releasing` even when Kitsu or anime-offline-database still reports `Upcoming`.

Airing-state normalization also treats any anime with a known next airing episode greater than 1 as `Airing`, because at least one prior episode has already aired. This prevents fallback `Upcoming` metadata from marking split-cour or mid-season entries as `Not Yet Aired`.


