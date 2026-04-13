# Agents Private

`/local/agents/private` stores deployment-local orchestrator state.

This tree is not a global framework contract; it is backup/restore state for this instance.

Canonical private roots:

- `shared/wiki/` -> live wiki runtime payload
- `crons/` -> node cron state buckets
- `plugins/memory/` -> private memory provider runtime data
- `skills/` -> shared mutable skills pool mounted by all nodes
- `scripts/backup/` -> local backup/restore entrypoints
