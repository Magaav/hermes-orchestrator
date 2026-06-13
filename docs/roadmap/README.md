# Roadmap Workspace

This workspace tracks Hermes Orchestrator work larger than routine operational
changes. Roadmap status never upgrades product/runtime claims.

## Track Index

| Track | Focus | Claim Status | Current Routing |
| --- | --- | --- | --- |
| `space-os` | Space OS direction, wasm-agent parity, embedded agent path, cloud/client state, browser-engine gates | future | Current implemented pieces route to `plugins/wasm-agent/README.md`; track detail: [space-os/README.md](space-os/README.md) |
| `guard` | Host doctor loop, guard logs, alerts, bounded restart remediation | implemented-unverified | Verify through `scripts/public/guard/README.md` and focused guard smoke before claiming runtime status; track detail: [guard/README.md](guard/README.md) |
| `wiki-engine` | Markdown-native wiki, proposal governance, graph routing, self-healing, observability | implemented-unverified | Verify current wiki commands/artifacts before claiming delivered status; track detail: [wiki-engine/README.md](wiki-engine/README.md) |
| `hermes-plugin-extension-points` | Upstream Hermes Agent extension seam proposal | proposal | Proposal only; track detail: [hermes-plugin-extension-points/README.md](hermes-plugin-extension-points/README.md) |

## Documentation Truth Invariant

Documentation must describe the current software, not intended behavior, unless a section is explicitly labeled as roadmap, proposal, future work, risk, or open question.

When runtime/codeflow behavior and documentation disagree, inspect the current implementation and update the docs to match reality. If code is changed to match intended behavior, update docs in the same change so they describe the new actual state. Every code CRUD change must include a docs-sync check.

Before major wasm-agent, WASM browser, Space OS, or cloud-client evolution, the
repo must pass a pre-evolution documentation sync gate: stale claims are pruned
or relabeled, partial capabilities are named as partial, and generated/upstream
runtime folders are not edited internally just to create coverage.

## Roadmap Principles

- Keep CLI workflows (`horc`) as the source of truth for operations.
- Preserve current node architecture and governance contract (`orchestrator` and `worker` roles).
- Avoid changing stable path contracts (for example `/local/logs/nodes/<node>/...`) without explicit migration notes.
- Treat automation safety as a hard requirement: bounded actions, observability, rollback-first design.
- Preserve compatibility with Hermes Agent mainline and Space Agent upstream. Prefer plugins, modules, customware bundles, components, hooks, and extension points over core edits.
- If a roadmap goal requires core behavior that does not have a safe extension seam, design the smallest upstreamable PR/seam before implementing local patches.

## Current State Rules

- CLI remains the canonical control plane unless a verified product doc says
  otherwise.
- Product/runtime truth lives in the owning plugin/native/script docs.
- Space OS is not a verified cloud product here; implemented pieces route to
  `plugins/wasm-agent`.
- Implementation commits should reference their track document and include
  verification notes.
