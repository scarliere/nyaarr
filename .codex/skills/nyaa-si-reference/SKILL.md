---
name: nyaa-si-reference
description: Nyaa.si domain reference for Codex work involving nyaa.si search URLs, categories, filters, RSS feeds, torrent detail pages, magnet links, .torrent downloads, anime release metadata extraction, title parsing, seed/leech/download counts, or integrations that consume nyaa.si results.
---

# Nyaa.si Reference

## Use This Skill

Read `references/nyaa-si-guide.md` before implementing nyaa.si scraping, RSS ingestion, metadata extraction, or torrent download behavior.

For implementation work:

1. Prefer RSS or stable page attributes over brittle visual scraping.
2. Keep raw Nyaa fields and parsed metadata separate.
3. Preserve exact torrent title, infohash, magnet link, category, uploader, timestamp, size, seeders, leechers, and completed downloads when available.
4. Handle missing or malformed rows defensively; Nyaa is public HTML, not a guaranteed API.

## Reference Files

- `references/nyaa-si-guide.md`: URL formats, RSS feed behavior, category/filter notes, .torrent extraction, metadata parsing, and dos and don'ts.
