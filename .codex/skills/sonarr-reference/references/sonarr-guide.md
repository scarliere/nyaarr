# Sonarr Guide

## Core Model

Sonarr manages TV/anime series and decides whether releases are wanted, downloadable, and importable.

Important entities:

- **Series**: A show record, usually linked to TheTVDB and stored under a root folder.
- **Episode**: A numbered airing unit. Sonarr tracks season number, episode number, title, air date, monitored status, and file state.
- **Episode file**: The imported media file associated with one or more episodes.
- **Quality profile**: Allowed qualities and cutoff. Do not treat "best available" as always wanted; cutoff matters.
- **Language profile / language**: Language constraints are separate from quality in newer Sonarr versions.
- **Indexer**: Search source for releases.
- **Download client**: Receives a selected release and returns completed downloads for import.
- **Import**: Sonarr links a completed download to known episodes, validates it, renames/moves/hardlinks/copies it, and updates episode files.

## API Notes

Common API patterns:

- Use the API key header `X-Api-Key` unless existing project code uses query auth.
- API v3 paths usually live under `/api/v3/...`.
- Common resources include `/series`, `/episode`, `/episodefile`, `/qualityprofile`, `/language`, `/queue`, `/history`, `/wanted/missing`, `/command`, `/release`, `/calendar`.
- Commands are asynchronous. Posting a command returns a command object; poll command status instead of assuming immediate completion.
- Respect pagination where available. Do not assume all endpoints return small lists.

When integrating:

- Keep Sonarr IDs distinct from TVDB/TMDB/IMDb IDs and local database IDs.
- Preserve timezone-aware datetimes. Sonarr often serializes UTC timestamps with `Z`.
- Do not infer monitored state from file presence; monitored is a user preference.
- Do not silently mutate quality profiles, root folders, tags, or monitored state without explicit user intent.

## Release Decision Concepts

Sonarr evaluates releases using series matching, episode parsing, quality, language, rejection rules, release profile rules, existing file state, monitored status, cutoff, and queue/history state.

For matching logic:

- Parse title into series title, season/episode or absolute episode, quality, source, codec, release group, proper/repack, and language when present.
- Preserve the original release title even after parsing.
- Treat anime carefully: absolute episode numbering and season/episode numbering may both appear.
- Handle multi-episode releases and season packs explicitly.
- Avoid accepting a release only because text contains the show name; validate episode identity.
- Keep "unknown" as a valid parsed state that blocks automatic action unless the caller requested manual handling.

## Import Behavior

Completed download import is stricter than "download succeeded".

Check:

- The download client item can be mapped to a known series and episode.
- The file extension is media-like and not a sample, archive, subtitle-only, or unrelated file.
- The target episode is monitored or otherwise intentionally imported.
- Quality and language can be parsed or accepted by manual override.
- Existing episode file replacement rules allow the new file.
- The file path is accessible from Sonarr's runtime environment, not just from the caller's environment.

Do not:

- Move files out from under Sonarr unless Sonarr is the owner of that operation.
- Assume hardlink support across filesystems.
- Delete downloads after import unless Sonarr/download-client settings explicitly do so.

## Naming And Metadata

Sonarr naming is user-configurable. Avoid hardcoding final media filenames unless the user asks to implement a naming format.

Keep these fields available when possible:

- Original release title
- Series title and Sonarr series ID
- Season and episode numbers, or absolute episode number
- Episode title
- Quality and quality revision
- Language
- Release group
- Source path and imported destination path
- Download client ID and indexer

## Dos

- Use Sonarr's API as the source of truth for series, episode, profile, queue, and history state.
- Preserve raw upstream metadata alongside parsed fields.
- Make parsers conservative and observable: return rejection reasons, not only booleans.
- Add fixtures for anime, season packs, multi-episode releases, repacks/proper, and malformed titles.
- Prefer idempotent operations. Retrying should not duplicate imports or queue items.
- Log enough context to explain why a release was accepted, rejected, or skipped.

## Don'ts

- Do not bypass Sonarr's release decision logic unless the user explicitly asks for manual import or override behavior.
- Do not assume every show uses `SxxEyy`; anime and specials often differ.
- Do not equate RSS appearance with wanted status.
- Do not assume a successful torrent download means Sonarr imported it.
- Do not strip release group, quality, or revision metadata during normalization.
- Do not change user configuration as a side effect of search, parse, or import tasks.
