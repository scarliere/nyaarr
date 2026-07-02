# Codex Instructions

## Project Defaults

This repository is primarily a Python Flask app.

Prefer Python-native project structure, tooling, and tests unless the task clearly requires another language:

- Put application code under an appropriate package directory rather than loose scripts once the project structure is established.
- Use Flask for the web application layer.
- Default the local Flask app port to `1269` unless the user or deployment environment specifies another port.
- Prefer `pytest` for tests.
- Use typed, explicit data models for Sonarr and nyaa.si metadata where practical.
- Keep network-facing code isolated behind small clients/adapters so parsing and decision logic can be tested with fixtures.
- Do not rely on live Sonarr or nyaa.si access for deterministic tests; use local fixtures for API, RSS, HTML, torrent, and magnet examples.

## Knowledgebase

Maintain human-readable implementation notes in `knowledgebase/`.

For every new implementation or meaningful behavior change:

- Add or update a focused `.md` file in an appropriate `knowledgebase/` subdirectory.
- Document what changed, why it exists, important files/routes/configuration, and current limitations.
- Keep entries concise enough for a new contributor to understand the app without reading every source file first.
- Do this in the same change as the code so documentation does not drift.

## Local Skills

This repository keeps project-local Codex skills under `.codex/skills`.

Before doing Sonarr-related work, read:

- `.codex/skills/sonarr-reference/SKILL.md`
- `.codex/skills/sonarr-reference/references/sonarr-guide.md`

Before doing nyaa.si, torrent metadata, RSS ingestion, or anime release parsing work, read:

- `.codex/skills/nyaa-si-reference/SKILL.md`
- `.codex/skills/nyaa-si-reference/references/nyaa-si-guide.md`

If a task touches both Sonarr and nyaa.si, use both local skill references before making behavior decisions.
