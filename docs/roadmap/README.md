# Roadmap Workspace

This workspace tracks Hermes Orchestrator roadmap items that are larger than routine operational changes.

The goal is to keep the root README focused on current behavior while documenting exploratory tracks in dedicated documents.

## Track Index

| Track | Focus | Status | Link |
| --- | --- | --- | --- |
| `space-os` | Pre-evolution documentation sync, Space Agent module strategy, Colmeio PWA direction, and WASM browser-engine R&D gate | Docs gate frozen; module seam audit next | [docs/roadmap/space-os/README.md](space-os/README.md) |
| `guard` | Host doctor loop, canonical guard logs, Discord alerts, bounded restart remediation, activity timeline dependency | V1 implemented | [docs/roadmap/guard/README.md](guard/README.md) |
| `wiki-engine` | Shared markdown-native wiki for durable orchestrator knowledge, proposal governance, graph routing, self-healing, and observability | Delivered | [docs/roadmap/wiki-engine/README.md](wiki-engine/README.md) |
| `hermes-plugin-extension-points` | Upstream Hermes Agent API proposal for true Discord governance, Discord app-command plugins, and final-response transforms | Proposal drafted | [docs/roadmap/hermes-plugin-extension-points/README.md](hermes-plugin-extension-points/README.md) |

## Documentation Truth Invariant

Documentation must describe the current software, not intended behavior, unless a section is explicitly labeled as roadmap, proposal, future work, risk, or open question.

When runtime/codeflow behavior and documentation disagree, inspect the current implementation and update the docs to match reality. If code is changed to match intended behavior, update docs in the same change so they describe the new actual state. Every code CRUD change must include a docs-sync check.

Before major Hermes Space UI, WASM browser, Space OS, or cloud-client evolution, the repo must pass a pre-evolution documentation sync gate: stale claims are pruned or relabeled, partial capabilities are named as partial, and generated/upstream runtime folders are not edited internally just to create coverage.

## Roadmap Principles

- Keep CLI workflows (`horc`) as the source of truth for operations.
- Preserve current node architecture and governance contract (`orchestrator` and `worker` roles).
- Avoid changing stable path contracts (for example `/local/logs/nodes/<node>/...`) without explicit migration notes.
- Treat automation safety as a hard requirement: bounded actions, observability, rollback-first design.
- Preserve compatibility with Hermes Agent mainline and Space Agent upstream. Prefer plugins, modules, customware bundles, components, hooks, and extension points over core edits.
- If a roadmap goal requires core behavior that does not have a safe extension seam, design the smallest upstreamable PR/seam before implementing local patches.

## Current State

The UI and Guard tracks now have concrete V1 contracts, but both remain intentionally bounded:

- CLI remains the canonical control plane
- Guard remains restart-only for automated remediation
- UI remains an augmentation layer over host-side orchestration and logs through
  `/local/plugins/hermes-space-ui`
- Space OS is not yet implemented as a cloud product; its roadmap is now past
  the initial docs sync gate and points next to Space Agent module seams and
  WASM browser-engine feasibility.

Implementation commits should reference their track document and include verification notes.
