# Roadmap Workspace

This workspace tracks Hermes Orchestrator roadmap items that are larger than routine operational changes.

The goal is to keep the root README focused on current behavior while documenting exploratory tracks in dedicated documents.

## Track Index

| Track | Focus | Status | Link |
| --- | --- | --- | --- |
| `wasm-ui` | Visual control plane, Guard observability, agent timeline UX, high-performance analysis paths | Implementation in progress | [docs/roadmap/wasm-ui/README.md](wasm-ui/README.md) |
| `guard` | Host doctor loop, canonical guard logs, Discord alerts, bounded restart remediation, activity timeline dependency | V1 implemented | [docs/roadmap/guard/README.md](guard/README.md) |
| `wiki-engine` | Shared markdown-native wiki for durable orchestrator knowledge, proposal governance, graph routing, self-healing, and observability | Delivered | [docs/roadmap/wiki-engine/README.md](wiki-engine/README.md) |

## Roadmap Principles

- Keep CLI workflows (`horc`) as the source of truth for operations.
- Preserve current node architecture and governance contract (`orchestrator` and `worker` roles).
- Avoid changing stable path contracts (for example `/local/logs/nodes/<node>/...`) without explicit migration notes.
- Treat automation safety as a hard requirement: bounded actions, observability, rollback-first design.

## Current State

The UI and Guard tracks now have concrete V1 contracts, but both remain intentionally bounded:

- CLI remains the canonical control plane
- Guard remains restart-only for automated remediation
- UI remains an augmentation layer over host-side orchestration and logs

Implementation commits should reference their track document and include verification notes.
