# Public Plugins

`/local/plugins/public` is the canonical git-tracked plugin root for Hermes Orchestrator.

## Public vs Private

- Public (`/local/plugins/public`): reusable runtime hooks, patchers, automation scripts, and templates.
- Private (`/local/plugins/private`): deployment-local command payloads, runtime stores, memory/wiki content, and mutable config.

## Plugin Surface

- `discord/`: Discord gateway hooks, slash bridge runtime, and related operational scripts.
- `hermes-core/`: orchestrator prestart pipelines and shared runtime patch orchestration.
- `wiki/`: legacy seed/templates only; canonical runtime wiki is private.

## Hermes-Orchestrator Synergy

- `horc` startup paths execute prestart scripts from this tree.
- Backup/restore workflows preserve the private plugin root while public plugin code stays in git.
- Script capabilities in `/local/scripts/public` are consumed by plugin hooks here for lifecycle, sync, and recovery routines.

## Versioning Rules

- Commit only public code and templates under `/local/plugins/public/**`.
- Do not commit runtime state under `/local/plugins/private/**`.
- Keep secrets out of both trees.

## See Also

- [`../README.md`](../README.md)
- [`../private/README.md`](../private/README.md)
- [`../../docs/features/plugins.md`](../../docs/features/plugins.md)
