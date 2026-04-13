# Roadmap Workspace

This workspace tracks Hermes Orchestrator roadmap items that are larger than routine operational changes.

The goal is to keep the root README focused on current behavior while documenting exploratory tracks in dedicated documents.

## Track Index

| Track | Focus | Status | Link |
| --- | --- | --- | --- |
| `wasm-ui` | Visual control plane exploration, high-performance rendering paths, observability UX | Exploring | [docs/roadmap/wasm-ui/README.md](wasm-ui/README.md) |
| `guard` | Background process monitoring, watch patterns, `/local/logs/` routing, Discord alerts, bounded remediation | Exploring | [docs/roadmap/guard/README.md](guard/README.md) |
| `wiki-engine` | Shared markdown-native wiki for durable orchestrator knowledge, proposal governance, graph routing, self-healing, and observability | Delivered | [docs/roadmap/wiki-engine/README.md](wiki-engine/README.md) |

## Roadmap Principles

- Keep CLI workflows (`horc`) as the source of truth for operations.
- Preserve current node architecture and governance contract (`orchestrator` and `worker` roles).
- Avoid changing stable path contracts (for example `/local/logs/nodes/<node>/...`) without explicit migration notes.
- Treat automation safety as a hard requirement: bounded actions, observability, rollback-first design.

## Current State

Both tracks are active design/prototyping efforts. They are not production guarantees.

Implementation commits should reference their track document and include verification notes.
