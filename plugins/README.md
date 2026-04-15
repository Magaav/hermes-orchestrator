# Plugins

`/local/plugins` is the plugin feature root for Hermes Orchestrator.

## Why This Exists

Plugins are split between reusable framework capabilities and deployment-local runtime state. This lets the orchestrator evolve shared features safely while keeping local secrets and mutable data outside versioned code paths.

## Directory Segregation

- `public/`: git-tracked plugin code, hooks, scripts, and templates.
- `private/`: local runtime payloads, command registries, memory/wiki data, and mutable plugin state.

## Hermes-Orchestrator Integration

- Worker nodes mount public/private plugin roots from this directory.
- `horc` lifecycle and backup flows include private plugin state for recovery.
- Script feature modules under `/local/scripts` and plugin hooks here are designed to work together.

## Read Next

- [`public/README.md`](public/README.md)
- [`private/README.md`](private/README.md)
- [`../docs/features/plugins.md`](../docs/features/plugins.md)
