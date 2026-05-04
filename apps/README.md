# Apps

`/local/apps` contains source-owned application surfaces that are part of
Hermes Orchestrator but are not the core `horc` CLI.

## Current Apps

- `wasm-ui/`: experimental browser UI for fleet observability, Guard summaries,
  agent activity views, and safe node operations.

## Boundaries

Apps here should treat `horc`, `/local/scripts/public/clone/clone_manager.py`,
and documented APIs as the operational source of truth. They should not become
alternate lifecycle controllers with private behavior.

The existing `wasm-ui` app is not the future Space OS WASM browser-engine
runtime. That future work is tracked in `/local/docs/roadmap/space-os/README.md`
until implemented.
