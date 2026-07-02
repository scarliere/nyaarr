# nyaarr
To create a Sonarr like experience for downloading anime

## Metadata providers

Add Anime metadata search uses this fallback order:

1. AniList live GraphQL API
2. anime-offline-database managed local cache
3. Kitsu live JSON:API
4. TMDB live API, only when configured

The anime-offline-database fallback is cached automatically in `data/cache/` and checked for updates weekly.

To override the managed cache, either:

- Place `anime-offline-database-minified.json` or `anime-offline-database.json` in `data/`
- Or set `ANIME_OFFLINE_DATABASE_PATH` to the JSON file path

For TMDB fallback, set either `TMDB_BEARER_TOKEN` or `TMDB_API_KEY`.

## ffprobe for media quality tags

Nyaarr uses `ffprobe` to sample one local media file per imported anime folder and tag quality such as `720p` or `1080p`.

Install a repo-local copy:

```powershell
python scripts\install_ffprobe.py
```

The installer places binaries under `tools/ffmpeg/bin/`, which is ignored by git. Nyaarr resolves `ffprobe` in this order:

1. `NYAARR_FFPROBE_PATH`
2. `tools/ffmpeg/bin/ffprobe.exe`
3. `ffprobe` on `PATH`
