# Plugins

`/local/plugins` is the plugin feature root for Hermes Orchestrator.

## Why This Exists

Plugins are split between reusable framework capabilities and deployment-local runtime state. This lets the orchestrator evolve shared features safely while keeping local secrets and mutable data outside versioned code paths.

## Directory Segregation

- `discord-slash-commands/`: canonical host plugin package for Discord slash UX; active code lives here while mutable state lives per node under `workspace/plugins/discord-slash-commands/cache`.
- `exhaust/`: canonical host plugin package for exhaust-mode behavior.
- `final-response-changed-files/`: canonical host plugin package for final response changed-file summaries.
- `wasm-agent/`: active host plugin package for the WASM workspace, Hermes bridge, and Hermes Agent UI parity shell; versioned module firmware lives under `wasm-agent/public/modules/`, while mutable local state, including bridge state and embedded assistant attachment assets, lives under `wasm-agent/state/`.

## Hermes-Orchestrator Integration

- Worker nodes mount standalone plugin roots directly when enabled.
- Gitignored compatibility/migration state may still be read by specific
  bootstraps when documented by that plugin, but new plugin code and mutable
  state should live in the standalone package or node-local cache named by that
  package.
- `horc` lifecycle and backup flows preserve node-local plugin caches and gitignored plugin state.
- Script feature modules under `/local/scripts` and plugin hooks here are designed to work together.

## Read Next

- [`discord-slash-commands/README.md`](discord-slash-commands/README.md)
- [`wasm-agent/README.md`](wasm-agent/README.md)
- [`exhaust/README.md`](exhaust/README.md)
- [`final-response-changed-files/README.md`](final-response-changed-files/README.md)
- [`../docs/features/plugins.md`](../docs/features/plugins.md)
