# Calendar

The calendar shows saved anime that have a known next air date.

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
- AniList search now requests `nextAiringEpisode` and stores the next episode date when available.
- Kitsu `startDate` and TMDB `first_air_date` can seed a date-only calendar entry when that date is today or in the future.
- The Add Anime form posts schedule fields into the local JSON library so calendar rendering does not require live provider access.
- Opening the calendar refreshes existing saved anime that are airing, not yet aired, or unknown and have stale schedule metadata.
- Opening the anime dashboard also recalculates and persists derived library/airing tags, so provider mapping fixes such as Kitsu `Current` to `Airing` are applied to existing saved records.

## Important Files

- `nyaarr/__init__.py`: `/calendar` route and Add Anime schedule-field persistence.
- `nyaarr/app_state.py`: `refresh_library_airing_schedule()` updates existing saved anime before calendar rendering.
- `nyaarr/app_state.py`: `calendar_model()` builds week/month day grids and the upcoming-airings list from saved library data.
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

Before rendering, `/calendar` refreshes schedule metadata for saved anime whose airing state is `Airing`, `Not Yet Aired`, or `Unknown`, unless that title was checked recently. The default refresh interval is 12 hours and can be changed with `NYAARR_AIRING_REFRESH_MAX_AGE_SECONDS`.

## Current Limitations

- Only metadata providers that expose a usable future/current air date populate the calendar. AniList provides exact next-episode timestamps through `nextAiringEpisode`; Kitsu and TMDB can provide date-only first/start air dates.
- Exact provider timestamps are stored as UTC but displayed and date-bucketed in the configured display timezone. Date-only fallback entries display `TBA`.

## Display Format

Displayed date labels use day month year order, for example 24 Jun 2026. Exact calendar times use `HH:MM <timezone>`, defaulting to `GMT+8` until changed in Settings. Machine values in URLs, form fields, and stored metadata remain ISO YYYY-MM-DD or UTC timestamps for parsing and interoperability.

## Airing Status Priority

Schedule refreshes now prefer an existing AniList provider ID before falling back to title search. This keeps saved anime aligned with AniList status changes such as `Releasing` even when Kitsu or anime-offline-database still reports `Upcoming`.

Airing-state normalization also treats any anime with a known next airing episode greater than 1 as `Airing`, because at least one prior episode has already aired. This prevents fallback `Upcoming` metadata from marking split-cour or mid-season entries as `Not Yet Aired`.


