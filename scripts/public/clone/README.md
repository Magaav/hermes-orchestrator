# Clone Manager And horc

`scripts/public/clone` owns the primary Hermes Orchestrator lifecycle engine and
CLI wrappers.

## Current Entry Points

- `horc.sh`: primary operator CLI wrapper.
- `hord.sh`: compatibility alias for `horc`.
- `clone.sh`: compatibility alias for `horc`.
- `clone_manager.py`: lifecycle engine for start, stop, status, logs, backup,
  restore, update, governance prompt generation, and Space UI helper commands.
- `tests/`: focused tests for governance prompt and gateway-state behavior.

## Documentation Sync

When CLI behavior, node lifecycle semantics, env handling, plugin bootstrap, or
Space UI helper commands change, update `/local/docs/commands/horc.md`, the
root README, and nearby plugin/feature docs as needed.

`horc` remains the canonical operational control plane. UI and plugin surfaces
should call into this boundary rather than inventing parallel lifecycle rules.
