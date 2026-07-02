# Add Anime Flow

The Add Anime flow is a Sonarr-style metadata search workspace.

## Route

- Page URL: `/add`
- Async search URL: `/add/search`
- Add URL: `/anime`
- Query parameter: `q`
- Page handler: `add_anime()` in `nyaarr/__init__.py`
- Search handler: `add_anime_search()` in `nyaarr/__init__.py`
- Add handler: `add_anime_to_library_route()` in `nyaarr/__init__.py`

Example:

```text
http://127.0.0.1:1269/add?q=frieren
```

## UI Behavior

The topbar `Add Anime` action links to `/add`.

The `/add` page renders immediately and then starts metadata search from inside the loaded page when `q` is present. This avoids a blank browser loading tab during provider requests. The page clears the dashboard body and shows:

- Page heading: `Add Anime`
- Metadata search input
- An in-page loading state while `/add/search` is running
- Provider notices when fallbacks or configuration issues occur
- Result cards when metadata is found
- Working result filter and sort controls
- Add buttons that post selected metadata into the client-local JSON anime library through fetch, showing the action state on the current page before redirecting to the anime list
- A per-result resolution dropdown immediately left of Add. It defaults to `Up to: 1080p` and supports `1080p`, `720p`, and `BD`.
- Empty state when no query or no results exist

## Filter And Sort

The results toolbar submits controls through query parameters:

- `status`: filters normalized result status. Supported values are `all`, `finished`, `releasing`, `not_yet_released`, `cancelled`, `hiatus`, and `unknown`.
- `sort`: sorts the current result set. Supported values are `relevance`, `title`, `year_desc`, `year_asc`, `rating_desc`, and `episodes_desc`.
- Changing either dropdown immediately reloads the results panel through `/add/search` without navigating away from the loaded page.
- The Clear button preserves `q` and resets filter/sort to defaults by linking back to `/add?q=<query>`.

Implementation:

- `nyaarr/result_controls.py` owns status filter and sort option definitions.
- `add_anime()` normalizes incoming controls and renders only the page shell. It does not call metadata providers.
- `add_anime_search()` performs provider search, applies result controls, and returns rendered `_metadata_results.html` as JSON for the loaded page to insert.
- `nyaarr/templates/add_anime.html` renders the search shell, in-page loading state, async result loader, and fetch-based Add actions.
- If provider results exist but the current filter removes all of them, the results panel and toolbar stay visible and an in-panel empty state explains that no results match the current filter.

## Result Card Fields

Each result uses a normalized metadata shape:

- `title`
- `original_title`
- `year`
- `status`
- `episodes`
- `season_number`
- `runtime`
- `genres`
- `studio`
- `source`
- `rating`
- `synopsis`
- `poster`
- `provider_ids`

The rating badge displays a heart marker next to the numeric rating so the score is visually distinct from other metadata.

Season identity is posted with the selected anime. Provider results infer `season_number` from title metadata such as `Season 2`, `S2`, `II`, or similar markers; entries without an explicit marker default to season 1.
If a posted season value is missing or invalid, the add route falls back to season 1.

Each added anime stores the selected quality preference:

- `1080p`: search up to 1080p, then fall back to lower stated resolutions or unstated-resolution releases.
- `720p`: search up to 720p, then fall back to lower stated resolutions or unstated-resolution releases.
- `BD`: explicitly permits BluRay/BD/BDRip/BDMV/remux releases to be indexed and selected.

After an anime is added, app state checks the configured root folder for a matching anime subfolder and counts existing media files as local episodes. If no root folder is configured yet, the anime is still added to the anime list but its library state becomes `Undownloadable` while it has missing episodes. The dashboard shows this as an orange badge. Hovering the badge explains: `No root folder selected, Nyaarr is unable to find a folder to place this anime into`.

The dashboard poster bar uses this local episode count against the total expected episodes, or against the latest aired episode when an airing anime has no confirmed total episode count. If an airing anime has a confirmed total, the bar uses downloaded episodes divided by the full expected total. Bar color follows the status tone: completed is green, airing is cyan, not-yet-aired is yellow, and undownloadable is a darker burnt orange so it does not read as the same warning tone as not-yet-aired. Not-yet-aired and undownloadable titles render a full-width bar as a clear state marker even though missing-episode calculations remain unchanged internally.

After the local episode check, the add route stores queued torrent-search state and returns immediately. Nyaa searches and qBittorrent dispatch run from the background maintenance tick so the Add button can redirect without waiting on indexer, download-client, or external request spacing delays. If the user supplies a Nyaa/magnet/torrent link while adding, Nyaarr stores it as the first candidate for background dispatch instead of sending it during the form POST.

## Current Limitations

- The result `Add` button stores anime in a client-local JSON file under `data/user/`.
- Download completion import requires qBittorrent paths to be accessible from Nyaarr.
- Relevance ordering is provider-defined; other sort modes are app-side sorting over returned results.
