# User Data

Nyaarr stores client-local user state as JSON under `data/user/`.

## Database File

Default path:

```text
data/user/anime-library.json
```

Override:

```text
NYAARR_USER_DATABASE_PATH=<path>
```

## Metadata Cache

Resolved root-folder metadata is cached separately:

```text
data/cache/resolved-anime-metadata.json
```

Override:

```text
NYAARR_RESOLVED_METADATA_CACHE_PATH=<path>
```

## Behavior

- `nyaarr/app_state.py` creates the JSON file automatically when it is missing.
- The current schema has `schema_version`, `settings`, `anime`, and `ignored_torrents`.
- Reads and writes are protected by a process-local reentrant lock, and writes use a temporary file plus `os.replace` so updates are atomic at file level.
- Added anime and torrent finder candidates persist across Flask restarts.
- `settings.root_folder` stores the selected anime root folder. qBittorrent downloads target this folder and can use a configured remote path mapping when qBittorrent reports paths from another host/container.
- Saving a root folder scans immediate child folders and root-level media files, then imports detected anime as local library entries.
- Root folder imports preserve `local_path` and `episode_files`. They also store AniList metadata when confidently resolved, or `manual_verification_required` with `metadata_candidates` when uncertain.
- Confident root-folder metadata resolutions are cached by cleaned search title under `data/cache/` so future rescans do not need to call AniList for already resolved anime. Cache reuse validates year and season hints when the folder name includes them.
- Library entries store `library_state`. Finished anime with a known episode count and enough local media files are marked `Completed`; otherwise monitored entries remain `Monitored`.
- Root folder scans can store `media_info`, `quality_tag`, and `media_tags` when `ffprobe` is available. Set `NYAARR_FFPROBE_PATH`, install repo-local ffprobe with `python scripts/install_ffprobe.py`, or provide `ffprobe` on `PATH`.
- `ignored_torrents` stores rejected flagged torrent keys, usually by infohash, with the anime title, torrent URLs, flagged files, and rejection time. Candidate selection skips these keys so rejected compromised torrents are not retried.

## Git Policy

Generated user data is client-local and must not be uploaded.

`.gitignore` excludes:

```text
data/user/*
!data/user/.gitkeep
data/cache/*
!data/cache/.gitkeep
```

Only `data/user/.gitkeep` is committed so the directory exists in fresh clones.

## Current Limitations

- No multi-user accounts yet.
- Invalid or unreadable JSON is replaced with a new empty database.
- Root folder scanning is conservative and uses filesystem names when AniList metadata is unavailable or ambiguous.

