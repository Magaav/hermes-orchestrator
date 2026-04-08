# Plugins

Global plugin surface for Hermes Orchestrator.

## Purpose

- Keep shared plugin code in one place for all nodes.
- Keep runtime state separated from repository code.

## Layout

- `discord/`: Discord integration hooks, scripts, and runtime templates.
- `memory/`: shared memory runtime store (OpenViking/Viking indexes and state).

## Versioning Rules

- Commit code and templates only.
- Never commit runtime memory or local generated state.
- Never commit credentials/secrets under `plugins/`.

Examples:

- tracked template: `plugins/discord/discord_users.json.example`
- not tracked runtime state: `plugins/discord/discord_users.json`
- not tracked runtime memory: `plugins/memory/**`
