# Flask App Architecture

Nyaarr is a Python Flask app that aims to provide a Sonarr-like experience for anime discovery and download automation.

## Runtime

- Entrypoint: `main.py`
- App factory: `nyaarr/__init__.py:create_app`
- Default bind host: `127.0.0.1`, configurable with `NYAARR_HOST`
- Default local port: `1269`, configurable with `NYAARR_PORT`
- Local dependency environment: `.venv`

`main.py` starts Flask with `use_reloader=False` so background preview launches do not create duplicate processes. The Windows launcher stops any existing Python process running this project's `main.py` or tray helper before starting a fresh Nyaarr instance, opens `http://127.0.0.1:1269` by default, and writes startup logs to `data/logs/`. It also starts `nyaarr/tray.py`, a Windows notification-area icon with `Open Nyaarr` and `Terminate Nyaarr` actions; terminating from the tray stops the Flask process tree and removes the icon. Set `NYAARR_PUBLIC_URL` to open a Cloudflare Tunnel URL instead. Set `NYAARR_HOST=0.0.0.0` only when the Flask process itself must accept LAN connections directly; Cloudflared running on the same PC can target `http://127.0.0.1:1269`.


## Periodic Maintenance

`nyaarr/maintenance.py` starts a daemon thread from `create_app()` unless `NYAARR_DISABLE_PERIODIC_MAINTENANCE=1` is set. The worker calls `run_periodic_maintenance_tick()` after a short startup delay and then every `NYAARR_PERIODIC_MAINTENANCE_INTERVAL_SECONDS`, defaulting to 60 seconds.

Each tick advances waiting app state without requiring a page render:

- Refreshes qBittorrent queue state, safety inspection, file selection, progress, completion, and import.
- Refreshes library completion and airing tags from local files.
- Refreshes stale torrent searches using `NYAARR_TORRENT_SEARCH_REFRESH_MAX_AGE_SECONDS`, defaulting to the periodic maintenance interval of 60 seconds.
- Attempts automatic torrent dispatch when root folder, qBittorrent, missing episodes, and candidate confidence criteria are all satisfied.
- Refreshes airing schedule metadata through the existing 12-hour TTL.
- Repairs missing or blocked poster URLs through alternate metadata providers, capped by `NYAARR_MAX_POSTER_REPAIRS_PER_TICK`.
- Routinely retries AniList metadata for anime that were resolved from fallback providers, capped by `NYAARR_MAX_ANILIST_METADATA_REFRESHES_PER_TICK` and throttled by `NYAARR_ANILIST_METADATA_REFRESH_MAX_AGE_SECONDS`. AniList poster repairs also preserve provider IDs, and existing AniList poster URLs can seed the AniList ID for later metadata and schedule refreshes.

External provider protection is intentionally conservative:
Root-folder saves avoid inline nyaa.si fan-out. Folder imports use cached metadata when available and may resolve uncached folders through the configured metadata provider fallback chain during the save request. Torrent searches for imported folders are queued for the capped background worker instead of running inside the settings save request.

Page renders are passive for external providers. Dashboard, Calendar, Manual Selection, Activity, and Settings reads must not directly call nyaa.si or metadata APIs; the maintenance worker owns those checks.

- Page renders call the same maintenance tick with external refreshes disabled, so opening the UI does not trigger nyaa.si or metadata API bursts.
- Background ticks cap nyaa.si torrent searches with `NYAARR_MAX_TORRENT_SEARCHES_PER_TICK`, defaulting to 2.
- Background ticks cap metadata/airing refreshes with `NYAARR_MAX_AIRING_REFRESHES_PER_TICK`, defaulting to 100.
- Background ticks cap AniList canonical metadata upgrade attempts with `NYAARR_MAX_ANILIST_METADATA_REFRESHES_PER_TICK`, defaulting to 3.
- External requests inside a tick are spaced by `NYAARR_EXTERNAL_REQUEST_SPACING_SECONDS`, defaulting to 2 seconds.
- Dispatch retries are throttled by `NYAARR_TORRENT_DISPATCH_RETRY_SECONDS`, defaulting to 5 minutes, so a temporarily unavailable qBittorrent client does not create a new notice every minute.
## Routes

- /: Anime dashboard, shown as Anime > Anime List in the sidebar.
- /anime/list: Anime List alias for the dashboard.
- `/anime/<library_id>`: Anime detail page with stored metadata, library state, and a Sonarr-style episode table derived from local files and qBittorrent queue records. A cog button at the far right of the title opens the AniList ID edit dialog for manual metadata correction. When an anime folder contains explicit season subfolders such as `Season 1` plus `Specials`, local TV episode rows and completion counts use the selected season folder instead of allowing specials to claim TV episode numbers.
- /anime/manual-selection: Low-confidence torrent candidates requiring user selection.
- /anime/manual-selection/select: POST endpoint that queues a user-selected candidate through the torrent safety flow.
- `/add`: Add Anime metadata search page. Accepts `q` query parameter.
- `/activity` and `/activity/<section>`: Activity pages for queued, history, and blocked torrent rows.
- `/settings`: Settings page for root folder configuration.
- `/settings/root-folder`: POST endpoint that saves the anime root folder and scans it for local imports.
- `/settings/root-folder/progress`: JSON endpoint polled by Settings for visible scan progress and by the shared shell to refresh sidebar Anime badge counts when a background root-folder scan finishes.
- `/settings/root-folder/delete`: POST endpoint that clears the saved anime root folder path.
- `/settings/status`: JSON endpoint used by the shell to refresh missing required settings every 10 minutes.
- `/system/status`: System status page with disk space, runtime details, uptime, and project links.

## Shared Sidebar Counts

The shared sidebar in `nyaarr/templates/base.html` renders zero-count defaults on first paint, then fetches current counts from `/sidebar-counts`. The shell also watches root-folder scan progress on every page and refreshes these counts when a background scan completes, so Anime, Manual Selection, and Metadata Review badges update even if the user left Settings.

Counts shown:

- `Total Anime`: total stored anime, shown with the dark-blue stat tone
- Anime: total stored anime, hidden when zero
- Manual Selection: yellow count of anime flagged for manual torrent selection, hidden when zero
- Metadata Review: yellow count of root-folder imports waiting for manual metadata verification, hidden when zero
- Activity: active incomplete Nyaarr-tracked downloads
- `Wanted`: anime entries with no torrent candidates yet
- `Settings`: yellow count badge with the number of missing required settings, currently root folder and download client




## Anime Menu

The shared sidebar Anime item is a native dropdown with Anime List and Manual Selection. Anime List renders the existing dashboard. Manual Selection lists anime flagged by the confidence scorer and allows a user-selected candidate to be queued manually. Numeric indicators are used consistently; zero-value indicators are hidden.
## Activity Menu

The shared sidebar Activity item is a native dropdown like System. It contains Queued, History, and Blocked. The top-level Activity badge counts only active incomplete Nyaarr-tracked downloads. Dropdown menu items use numeric indicators instead of arrows. Zero-value indicators are hidden. When the Activity dropdown is open, the badge is visually hidden from Activity and shown beside Queued when the active download count is nonzero.

Activity queued and blocked tables use columns for anime name, episode number, date added, resolution, time left, progress, and actions where relevant. History removes time left, adds date completed, removes the normal settings-panel width cap, uses fixed column proportions across the full Activity page width, and keeps denser rows so more completed items are visible. History only includes completed/imported queues, so it does not contribute to the Activity count. Queued includes active flagged torrents with Allow and Reject actions. Blocked lists rejected flagged torrents from `ignored_torrents`, and also does not contribute to the Activity count.
## Dashboard Library Stats

Anime List renders Health below the anime cards as a horizontal section. Anime List does not render Flagged Torrents or Torrent Finder side-panel sections; torrent review and candidate assignment belong to Activity and Manual Selection surfaces. Anime card episode counts render as centered grey pills with light text for contrast. The dashboard stat row shows `Total Anime`, `Completed`, `Airing`, and `Not Yet Aired`. `Total Anime` uses a distinct dark-blue stat tone so it does not blend into the dark panel background. `Completed` follows the completed tag tone, `Airing` follows the airing tag tone, and `Not Yet Aired` follows the upcoming tag tone. The old `Monitored` stat was removed because membership in the local anime list already means the title is monitored.
## Templates

- `nyaarr/templates/base.html`: Shared shell, sidebar, topbar, global search, Add Anime action, async content loader, async sidebar count refresh, and periodic Settings badge refresh.
- `nyaarr/templates/dashboard.html`: Dashboard content using the shared shell; anime cards link to per-anime detail pages.
- `nyaarr/templates/anime_detail.html`: Per-anime metadata summary and episode table.
- `nyaarr/templates/add_anime.html`: Search workspace and metadata result list.
- `nyaarr/templates/settings.html`: Root folder settings form, download client settings, and per-section missing-input warnings.
- `nyaarr/templates/manual_selection.html`: Manual torrent candidate assignment page using the same settings workspace, stats grid, panel, and activity table styling as the Activity section.
- `nyaarr/templates/events.html`: System Logs page, including the CSV download action.
- `nyaarr/templates/_partial_base.html`: Fragment-only template base used by async data routes.

## Static Assets

- `nyaarr/static/css/app.css`: Sonarr-inspired dark operational UI.
- `nyaarr/static/img/default-icon.png`: Default Nyaarr icon copied from `data/image/` and used for browser icons, the sidebar brand image, and poster fallbacks. The sidebar brand image sits above the Nyaarr title, spans the menu inner width, remains circular, and uses contain sizing so the source image is not cropped. Dashboard and calendar poster images also swap to this local icon when a remote metadata poster fails to load, which prevents broken remote CDN images from collapsing the card presentation.

The design uses:

- Dark fixed sidebar
- Dense topbar with search and actions
- Dashboard stat tiles
- Poster grid for anime library cards
- Health section below the anime cards for metadata and torrent notices
- Add Anime search results with poster, metadata, badges, and source labels

## Current Limitations

- Anime library state is stored in a client-local JSON database.
- There is no server database layer yet.
- Live metadata routes depend on external provider availability unless offline fallback data is configured.
- Torrent finder refreshes are handled by the capped background maintenance worker after Add or root-folder import queues the title.
## System Dropdown

The shared sidebar in `nyaarr/templates/base.html` includes click-to-open dropdown menus implemented with native `details` and `summary` markup, using numeric indicators instead of arrows. Status links to `/system/status`; Logs links to `/system/logs`. Styling lives in `nyaarr/static/css/app.css`, including a compact absolute dropdown on mobile navigation. The Status page gets host disk space, Python/Flask/platform details, app uptime, and project links from `nyaarr/system_status.py`; its uptime display continues ticking in the browser from the server-rendered process uptime. Disk rows mark the drive containing the configured anime root folder with a `Root Folder's Drive` pill beside the drive label.



## System Logs

System > Logs renders the retained client-local interaction list from `app_state.event_log_model()`. `/system/events` is kept as a compatibility alias for older links. Logs are recorded for library adds/updates, root folder and download-client settings changes, download-client connection tests, metadata verification, Nyaa search refreshes, periodic maintenance work, torrent dispatch, manual torrent selection/rejection, flagged torrent allow/reject decisions, qBittorrent queue disappearance, safety flagging, and completed imports.

The log is capped to the latest 200 entries in the user JSON database and displayed newest-first. `/system/logs.csv` exports the retained rows with date, category, anime, torrent, status, and message columns. The web table uses a logs-specific fixed layout that keeps the date/status columns compact and gives message text the widest column so long operational messages wrap instead of overlapping adjacent cells.








