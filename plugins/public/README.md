# Public Plugins

Canonical git-tracked plugin root for Hermes Orchestrator.

## Canonical Roots

- Public plugins (tracked): `/local/plugins/public`
- Private plugin runtime/config (local-only): `/local/plugins/private`

## Plugin Ownership

- `discord/`
  - Public: hook/runtime code, scripts, tests, docs, `*.example` templates.
  - Private: node command payloads and runtime config/state under `/local/plugins/private/discord`.
- `hermes-core/`
  - Public: shared orchestrator startup/verification logic and wiki engine code.
- `wiki/`
  - Public: reusable doctrine/templates/reference pages shared across instances.
  - Private runtime evolution: `/local/plugins/private/wiki`.
- `memory/`
  - Runtime data remains private/local and is never committed.

## Versioning Rules

- Commit only public code and templates under `/local/plugins/public/**`.
- Do not commit runtime data under `/local/plugins/private/**`.
- Keep secrets out of both trees.
