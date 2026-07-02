---
name: sonarr-reference
description: Sonarr domain reference for Codex work involving Sonarr behavior, APIs, import decisions, naming, quality profiles, release parsing, episode/series metadata, download-client integration, or compatibility with Sonarr conventions. Use whenever a task is Sonarr-related, including code changes, bug fixes, docs, tests, automation, or integrations that read from or write to Sonarr.
---

# Sonarr Reference

## Use This Skill

Read `references/sonarr-guide.md` before making Sonarr-related behavior decisions. Treat it as a local working reference for how Sonarr thinks about series, episodes, releases, imports, and download clients.

For implementation work:

1. Preserve Sonarr's existing terminology: series, season, episode, release, quality, language, root folder, monitored, download client, indexer, import.
2. Match the target Sonarr version or API shape already used by the project.
3. Prefer compatibility with Sonarr's API and behavior over inventing app-specific shortcuts.
4. Add tests around parsing, filtering, or import decisions when changing matching logic.

## Reference Files

- `references/sonarr-guide.md`: Core Sonarr concepts, API notes, metadata expectations, release parsing guidance, and dos and don'ts.
