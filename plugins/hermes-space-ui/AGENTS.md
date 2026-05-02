# AGENTS

## Purpose

`hermes-space-ui/` owns the external Hermes plugin that connects Space Agent to Hermes Orchestrator fleet control.

The plugin must keep Hermes-specific behavior outside Space Agent upstream. Space Agent changes should be proposed as generic Customware Bundle Interface seams, while this plugin carries the Hermes bundle manifests, bridge helpers, and deployment scripts.

## Ownership

This folder owns:

- `README.md`: operator-facing setup and architecture notes.
- `plugin.yaml`: plugin metadata for the Hermes plugin system.
- `server/`: local bridge API between Space Agent UI requests and Hermes Orchestrator operations.
- `scripts/`: lifecycle helpers for starting and stopping Space Agent and the bridge.
- `skills/`: Hermes-facing skills.
- `examples/`: JSON payload examples for bridge testing.
- `plugin-interface/`: Space Agent customware-bundle mirror and bridge helpers for Hermes-specific UI integration.
- `state/`: ignored runtime state, logs, downloaded Node, and Space Agent checkouts.

## Local Contracts

- Do not patch Hermes Agent core or Space Agent runtime files from this plugin.
- Hermes UI customization should live under `plugin-interface/` as installable customware-bundle source.
- Runtime state under `state/` is not a PR workspace and should not be treated as source.
- When an upstream Space Agent seam is missing, propose the generic seam upstream and keep the Hermes-specific consumer here.

## Development Guidance

- Keep bridge actions routed through Hermes Orchestrator boundaries.
- Keep bundle source readable and removable so it can be reapplied after Space Agent upgrades.
- Update this file and the nearest child `AGENTS.md` when adding a durable folder or changing ownership.
