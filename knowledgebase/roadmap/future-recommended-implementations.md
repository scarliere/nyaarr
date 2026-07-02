# Future Recommended Implementations

Nyaarr is currently suitable as an alpha project for trusted local use. Before broader deployment, prioritize the following improvements.

## Access Control

- Add application login before exposing Nyaarr outside a trusted LAN or VPN.
- Support a simple first-run admin account setup and password change flow.
- Store password hashes only; never store plaintext credentials.
- Add session expiry and CSRF protection for mutating routes.
- Document safe reverse-proxy options such as basic auth, Cloudflare Access, or Tailscale as interim protection.

## Data Safety

- Keep `data/user/`, `data/cache/`, generated images, and torrent artifacts out of Git.
- Add backup/export and restore flows for the local user database.
- Consider migration/version metadata for `anime-library.json` before changing stored schemas.
- Add a settings screen warning when download-client credentials or local paths are configured.

## Download And Import Hardening

- Add a visible import audit trail per anime, including source torrent, selected files, skipped files, destination paths, and cleanup actions.
- Add a manual repair action for completed torrents whose files are accessible but not recorded in `episode_files`.
- Expand batch import tests for duplicate filenames, partial imports, remote path mappings, and existing local folders.
- Add optional cleanup policy settings for imported torrents and superseded episode torrents.

## Operational Readiness

- Add health checks for configured root folder accessibility and qBittorrent reachability.
- Add a startup diagnostics page section for ignored local data paths and effective `.gitignore` expectations.
- Add structured log export with redaction for credentials and local paths.
- Add rate-limit and retry visibility for external metadata providers and nyaa.si RSS calls.

## Packaging

- Keep the alpha Windows `install.bat`, `install.ps1`, and `start.ps1` flow documented: install dependencies into `.venv`, create a desktop shortcut, start Flask on configurable `NYAARR_HOST`/`NYAARR_PORT`, and open the browser at local or `NYAARR_PUBLIC_URL`. For beta, consider a signed installer or bundled executable instead of relying on PowerShell execution policy bypass.
- Add a production run guide with recommended environment variables, reverse proxy notes, and backup paths.
- Add a Docker or service-manager example after path mapping behavior is stable.
- Add release checklist notes for tests, ignored local data, and alpha upgrade caveats.