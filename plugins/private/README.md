# Private Plugins

`/local/plugins/private` holds deployment-local plugin runtime state.

## Why It Exists

Private plugin data changes at runtime and can include sensitive or environment-specific payloads. Keeping this separate from public plugin code preserves clean version control and safer operations.

## Current Structure

- `discord/`: node command payloads and private Discord runtime config.
- `memory/`: private memory provider state and persisted memory assets.
- `wiki/`: canonical shared wiki runtime tree consumed across nodes.

## Hermes-Orchestrator Integration

- Worker nodes mount this directory as `/local/plugins/private`.
- `horc backup` includes this tree so runtime plugin state is restorable.
- `horc restore` reapplies this tree and re-links node mounts through clone manager.

## Synergies

- Public plugin hooks (`/local/plugins/public`) read/write data here.
- Script feature modules (`/local/scripts/public`) orchestrate lifecycle and backup paths that operate on this tree.
- Shared cron routines in `/local/crons` commonly call plugin-backed runtime capabilities.

## See Also

- [`../README.md`](../README.md)
- [`../public/README.md`](../public/README.md)
- [`../../docs/features/plugins.md`](../../docs/features/plugins.md)
