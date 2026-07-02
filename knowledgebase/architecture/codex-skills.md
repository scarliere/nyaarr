# Codex Skills

The repository keeps project-local Codex skill copies under `.codex/skills` so future Codex sessions can reference project domain guidance directly.

## Skills

- `.codex/skills/sonarr-reference`
- `.codex/skills/nyaa-si-reference`

## Repo Instructions

Root `AGENTS.md` tells Codex to read:

- Sonarr skill files before Sonarr-related behavior, API, import, release, episode, or integration work.
- nyaa.si skill files before nyaa.si search, RSS, torrent, metadata extraction, or release parsing work.
- Both skill references when a change touches both domains.

## Why This Exists

Nyaarr intentionally borrows Sonarr concepts while targeting anime and nyaa.si workflows. The local skills preserve the project vocabulary and guardrails:

- Use Sonarr terminology carefully where compatibility matters.
- Treat anime numbering and metadata as first-class concerns.
- Prefer RSS/stable metadata extraction for nyaa.si.
- Preserve raw upstream metadata alongside parsed fields.

## Maintenance Rule

If Sonarr or nyaa.si behavior guidance changes, update both the relevant `.codex/skills/...` file and this knowledgebase if the change affects app implementation.
