# Nyaarr

Nyaarr is a local-first anime library and download manager inspired by Sonarr. It helps you add anime, track missing episodes, search nyaa.si, send safe releases to qBittorrent, and import completed files back into your anime folders.

> Alpha software: run it on a trusted machine or LAN. First startup requires a local superadmin account; passwords are stored as non-reversible hashes under ignored user data.

## Features

- **Anime library dashboard** with poster cards, completion counts, airing status, and health notices.
- **Metadata search** through AniList, anime-offline-database, Kitsu, and optional TMDB fallback, with AniList reconciled as the final source of truth.
- **Root folder import** for existing anime folders, including metadata review for ambiguous matches and Jellyfin-compatible AniList `.nfo` files when identified.
- **Nyaa.si torrent search** using RSS, release parsing, confidence scoring, and preferred subber support.
- **qBittorrent integration** with paused safety inspection before downloads are resumed.
- **Batch support** that selects only wanted episode files and stages imports into the existing anime folder.
- **Manual selection** for low-confidence releases, no-candidate episodes, and user-supplied Nyaa/torrent/magnet links.
- **Activity views** for queued, completed, blocked, and flagged torrent decisions.
- **System status and logs** for disk space, runtime details, uptime, and recent automation events.

## Windows Alpha Install

From the repository folder, run:

```bat
install.bat
```

PowerShell users can also run:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer checks for Python 3, installs it with `winget` if missing, creates `.venv`, installs dependencies, attempts to install repo-local `ffprobe`, and creates a **Nyaarr** desktop shortcut.

The shortcut runs `start.ps1`, starts Nyaarr at `http://127.0.0.1:1269`, and opens it in your default browser.

## Manual Run

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
.\.venv\Scripts\python main.py
```

Then open `http://127.0.0.1:1269`.

## Configuration

Inside the app, configure:

- Anime root folder
- qBittorrent connection
- Optional remote path mapping
- Preferred subbers, defaulting to SubsPlease
- Display timezone

Optional environment variables:

- `TMDB_BEARER_TOKEN` or `TMDB_API_KEY` for TMDB metadata fallback
- `ANIME_OFFLINE_DATABASE_PATH` to use a custom offline anime database file
- `NYAARR_FFPROBE_PATH` to point at a specific `ffprobe` binary

## Data Safety

Nyaarr stores local state under `data/`:

- `data/user/` contains the SQLite state database, a JSON compatibility mirror, settings, auth hash, and session secret
- `data/cache/` contains metadata caches
- `data/logs/` contains launcher/runtime logs
- `data/image/` contains generated local shortcut icon assets

These paths are ignored by Git. Do not publish your local `data/user/anime-library.json`; it may contain private paths, download-client settings, and authentication metadata.

For test devices, reset Nyaarr to a fresh-client state with either cleaner:

```powershell
.\clear-local-data.ps1
python scripts\clear_local_data.py
```

Use `-Force` for PowerShell or `--force` for Python to skip the confirmation prompt in disposable test environments. The cleaners preserve `data/image/nyaarr.ico` so existing desktop shortcuts keep their icon after a data wipe.

## Development

Run tests with:

```powershell
python -m pytest
```

Project notes live in `knowledgebase/`.

Normal launches use Waitress with eight request threads. Set `NYAARR_WEB_THREADS`
to tune that bound. Background provider, library, and download work runs through
the durable SQLite job queue; set `NYAARR_JOB_WORKERS` to tune its bounded worker
pool independently.

## Status

Nyaarr is currently an alpha Flask app. It is best suited for local use while packaging, backup/restore, and broader deployment hardening are still being built.
