# UI Density And Action Hierarchy

## What changed

Desktop activity, episode, manual-selection, metadata-review, and log tables now favor one-line rows. Long titles, filenames, torrents, and messages use truncation with native title text or expandable details, while the existing small-screen table-to-card layout remains available.

Anime preferences, AniList correction, and library removal are grouped behind one Options dialog. Missing-episode torrent URL forms and secondary rejection/removal actions use progressive disclosure so the primary workflow remains compact.

Calendar entries link to anime detail pages, month cells collapse extra entries behind a +N more control, and users can jump directly to a date. Logs have in-page search/category/status filters and expandable copyable details.

Async page, activity, form, episode-title, and settings failures now expose retry or inline error feedback. Shared keyboard focus and reduced-motion rules cover the updated controls.

## Important files

- nyaarr/templates/anime_detail.html: anime options and episode source assignment.
- nyaarr/templates/calendar.html: linked entries, date jump, and month overflow.
- nyaarr/templates/activity.html, manual_selection.html, metadata_verification.html, and events.html: dense tables and action hierarchy.
- nyaarr/templates/settings.html: state-aware qBittorrent configuration and advanced fields.
- nyaarr/templates/base.html: Add Anime search and async recovery.
- nyaarr/static/css/app.css: shared table density, truncation, focus, responsive, and motion rules.

## Current limitations

- Truncated desktop values require their tooltip or expandable control to view the full content.
- Log filters apply to the newest server-provided rows; CSV export remains the complete export path.
- At 760px and below, rows intentionally become multi-line labeled cards instead of forcing horizontal single-line content.
