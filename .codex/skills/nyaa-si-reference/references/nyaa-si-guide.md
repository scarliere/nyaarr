# Nyaa.si Guide

## Stable Access Patterns

Nyaa.si is a public torrent index. Prefer RSS for ingestion and detail pages only when fields are missing from the feed.

Common URL shapes:

- Search HTML: `https://nyaa.si/?q=<query>&c=<category>&f=<filter>&s=<sort>&o=<order>&p=<page>`
- RSS: `https://nyaa.si/?page=rss&q=<query>&c=<category>&f=<filter>`
- Detail page: `https://nyaa.si/view/<id>`
- Torrent download: `https://nyaa.si/download/<id>.torrent`

Common query parameters:

- `q`: search text.
- `c`: category. Anime English-translated releases commonly use `1_2`; anime raw commonly uses `1_4`; use the category already required by the project.
- `f`: filter. Common values are `0` for no filter, `1` for no remakes, `2` for trusted only.
- `s`: sort field such as `seeders`, `leechers`, `downloads`, `size`, or `id`.
- `o`: sort order, commonly `desc` or `asc`.
- `p`: page number for HTML search results.

## RSS Feed Fields

RSS entries are usually the most stable ingestion source.

Preserve these values when present:

- `title`: exact torrent title.
- `link`: detail page URL.
- `guid`: stable item identifier, often detail URL or item ID.
- `pubDate`: publication time.
- `nyaa:seeders`, `nyaa:leechers`, `nyaa:downloads`: swarm stats.
- `nyaa:infoHash`: torrent infohash.
- `nyaa:category`, `nyaa:categoryId`: display category and machine category.
- `nyaa:size`: human-readable size.
- `nyaa:comments`: comment count.
- `nyaa:trusted`, `nyaa:remake`: booleans or boolean-like strings.
- `description`: may include links and summary HTML; treat as untrusted markup.

Implementation notes:

- Parse XML with a real XML/RSS parser that preserves namespaced elements.
- Convert counts to integers defensively.
- Parse size into bytes, but keep the original size string.
- Treat missing `infoHash` as recoverable if a magnet link or `.torrent` can be fetched.
- Do not rely on RSS item order for deduplication; use item ID, infohash, or detail URL.

## HTML Search And Detail Extraction

Use HTML only when RSS lacks required fields.

Search result rows commonly provide:

- Category icon/link
- Torrent title and detail URL
- Comment count
- `.torrent` download link
- Magnet link
- Size
- Date/time
- Seeders
- Leechers
- Completed downloads

Extraction guidance:

- Select anchors by URL pattern (`/view/<id>`, `/download/<id>.torrent`, `magnet:?`) rather than CSS position.
- Extract torrent ID from `/view/<id>` or `/download/<id>.torrent`.
- Extract magnet infohash from `magnet:?xt=urn:btih:<hash>` when available.
- Normalize relative links against `https://nyaa.si`.
- Keep numeric columns tied to their headers or known order with tests; table layouts can shift.
- Treat trusted/remake state as metadata, not a quality guarantee.

## Torrent And Magnet Handling

For `.torrent`:

- Fetch from `/download/<id>.torrent`.
- Expect binary bencoded data. Do not decode as text except through a bencode parser.
- Extract infohash from the torrent metainfo when needed by hashing the bencoded `info` dictionary.
- Preserve announce URLs and file list if needed for downstream clients.

For magnet links:

- Parse query parameters.
- `xt=urn:btih:<hash>` is the primary identifier.
- Preserve display name `dn`, trackers `tr`, and exact magnet URI.

Do not download torrent payload content. The `.torrent` file is metadata; media files are acquired by the user's torrent client.

## Anime Release Metadata Parsing

Torrent titles vary by release group. Keep parsing conservative and reversible.

Common fields:

- Release group, often `[Group]`.
- Series title.
- Episode number, sometimes absolute (`- 07`) or season/episode (`S02E07`).
- Resolution (`1080p`, `720p`, `2160p`).
- Source (`WEB`, `WEB-DL`, `BluRay`, `BD`, `HDTV`).
- Codec (`x264`, `x265`, `HEVC`, `AV1`).
- Audio (`AAC`, `FLAC`, `Opus`, channel layout).
- Subtitle type (`ENG SUB`, `Multi-Subs`, `Dual Audio`) when present.
- Container (`mkv`, `mp4`) when present.
- Release revision (`v2`, `v3`) or `REPACK`/`PROPER`.

Parsing rules:

- Store `raw_title` exactly.
- Produce `parsed` fields with confidence or rejection reasons.
- Do not strip bracketed groups blindly; bracketed text may contain quality, source, CRC, or subtitle info.
- Anime may use absolute numbering rather than seasons.
- CRC hashes are often 8 hex chars in brackets; preserve separately if detected.
- Avoid using title parsing as the only dedupe key. Prefer torrent ID or infohash.

## Dos

- Prefer RSS for scheduled polling.
- Use stable IDs: Nyaa ID, infohash, magnet URI, or detail URL.
- Preserve both raw and normalized metadata.
- Rate-limit requests and cache pages/results where practical.
- Include fixtures for RSS entries, HTML rows, magnets, and malformed titles.
- Validate `.torrent` downloads by content type or bencode parse, not file extension alone.

## Don'ts

- Do not scrape by visual column text without tests.
- Do not assume a category means language, quality, or compatibility with Sonarr.
- Do not assume seed counts are current after ingestion; they are snapshots.
- Do not execute or trust HTML from descriptions.
- Do not treat `.torrent` metadata as the downloaded media file.
- Do not rely on Nyaa availability for deterministic tests; use fixtures.
