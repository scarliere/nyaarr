# Download Client Settings

Nyaarr has a settings flow for connecting a torrent download client.

## What Changed

- Added a `Connect Torrent Client` panel under `/settings`.
- Added a plus button that opens an Add Download Client dialog.
- The dialog lists four torrent clients:
  - qBittorrent
  - Transmission
  - Deluge
  - uTorrent
- Only qBittorrent is enabled. The other clients are greyed out and disabled.
- The dialog includes a disclaimer that Nyaarr currently only supports qBittorrent.
- qBittorrent settings are saved under `settings.download_client` in the local user database.
- Saved qBittorrent clients can be tested from Settings. The `Test Connection` button sits at the right end of the configured host row and updates the page without a full refresh, showing a green-circle `Test success` tag beside the qBittorrent name on success. The status tag has reserved space so success/failure updates do not shift the settings block. The test uses qBittorrent's Web API version endpoint and performs a login first when credentials are configured.
- The Add Download Client dialog opens saved qBittorrent settings when a client already exists. Its footer can test the current textfield values without saving and can delete the saved client configuration.
- When an anime has missing episodes and a suitable Nyaa RSS candidate, Nyaarr sends the selected `.torrent` URL to qBittorrent paused with the configured category, root folder save path, and a safe anime folder name.
- Before resuming a Nyaarr-sent torrent, queue refresh reads qBittorrent file metadata and flags the whole torrent if any file is not a known anime video container. Flagged torrents can be allowed or rejected from Activity > Queued.
- When a partial anime falls back to a batch torrent, Nyaarr uses qBittorrent file priorities after torrent metadata loads so only files matching missing episode numbers are downloaded.
- qBittorrent settings include an optional remote path mapping. When enabled, completed import translates the configured qBittorrent remote prefix to a local path visible to Nyaarr before moving files into the anime root folder.
- Queue refresh preserves qBittorrent paused, stalled, and error states for Activity instead of treating those states as normal downloading.
- Completed imports validate candidate files before moving them: files must be supported media containers, must not look like samples, and must match wanted episode numbers when Nyaarr knows the wanted set.

## Manual Torrent Push Test Flow

A manual live test against qBittorrent should follow the same safety gate as normal library dispatch:

1. Load saved settings from `user_settings()["download_client"]` and create the configured qBittorrent client with `client_from_settings()`.
2. Add the supplied Nyaa `.torrent` URL with `/api/v2/torrents/add` using the configured category, Nyaarr tags, and `paused=true`.
3. Identify the added torrent by the new qBittorrent hash in that category.
4. Read `/api/v2/torrents/files` and run the same file-extension safety check as `_inspect_torrent_safety()`.
5. If every file is an allowed media container, start the torrent and monitor `/api/v2/torrents/info` until `progress` reaches `1.0` or `amount_left` is `0`.
6. For cleanup-only tests, delete the torrent with `deleteFiles=true` and verify the hash is no longer visible.

The 24 June 2026 live test with `https://nyaa.si/download/2120177.torrent` used configured qBittorrent `v5.1.4`, category `nyaarr`, and hash `a30958894ffc15584c7b4907fd2af628984f0c8b`. It passed safety inspection, downloaded to completion, and was deleted with data.

## qBittorrent Fields

The qBittorrent form follows the same general Sonarr download-client shape:

- Enable
- Name
- Host
- Port
- URL Base
- Username
- Password
- Category
- Use SSL
- Add Paused
- Remote Path Mapping
- Remote Path
- Local Path

## Important Files

- `nyaarr/templates/settings.html`: connect panel, client picker dialog, qBittorrent form.
- `nyaarr/__init__.py`: `/settings/download-client` POST route.
- `nyaarr/__init__.py`: `/settings/download-client/test` POST route.
- `nyaarr/__init__.py`: `/settings/download-client/delete` POST route.
- `nyaarr/app_state.py`: `save_download_client()` persistence, `delete_download_client()` removal, `test_download_client()` Web API check, torrent dispatch orchestration, and default settings.
- `nyaarr/qbittorrent_client.py`: isolated qBittorrent Web API adapter.
- `nyaarr/static/css/app.css`: dialog, client picker, and settings form styles.

## Current Limitations

- Unsupported clients are shown for roadmap visibility only.
- Passwords are stored in the local JSON settings file. This is acceptable for the current local-only app but should be revisited before remote or multi-user deployment.
- Import after download requires qBittorrent's completed path to be accessible from the Nyaarr process after optional remote path mapping is applied. Remote qBittorrent installations still need a real shared or mounted path.
- qBittorrent must expose torrent file metadata for safety inspection. Until metadata is available, Nyaarr keeps the torrent paused and reports `pending_safety`.
- If a completed torrent contains only sample files, unparseable episode files, or episodes outside the wanted set, Nyaarr leaves the queue as completed with `import_status=blocked` so it can be reviewed instead of silently moving the wrong file.
- qBittorrent `v5.1.4` returned HTTP `404` for `/api/v2/torrents/resume` during the live test. Nyaarr now falls back to `/api/v2/torrents/start` when `/resume` returns `404`.

## Settings Dialog Save

The qBittorrent settings dialog submits with fetch and expects JSON from `/settings/download-client`. On success, the browser follows the returned `redirect_url` back to Settings with the saved message. If the server returns non-JSON, an error, or an auth/login page, the dialog restores the Save button and shows the failure in the dialog status pill instead of staying stuck on `Saving`.

The save handler posts to the form action unless the clicked button explicitly defines `formaction`. This keeps Save on `/settings/download-client` while still allowing Delete to target `/settings/download-client/delete`.
