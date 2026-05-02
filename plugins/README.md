# Plugins

`/local/plugins` is the plugin feature root for Hermes Orchestrator.

## Why This Exists

Plugins are split between reusable framework capabilities and deployment-local runtime state. This lets the orchestrator evolve shared features safely while keeping local secrets and mutable data outside versioned code paths.

## Directory Segregation

- `discord-slash-commands/`: canonical host plugin package for Discord slash UX; active code lives here while mutable state lives per node under `workspace/plugins/discord-slash-commands/cache`.
- `exhaust/`: canonical host plugin package for exhaust-mode behavior.
- `final-response-changed-files/`: canonical host plugin package for final response changed-file summaries.
- `hermes-space-ui/`: canonical host plugin package for Space Agent UI integration; mutable local state lives under `hermes-space-ui/state/`.
- `public/`: optional legacy git-tracked plugin code, hooks, scripts, and templates when present.
- `private/`: optional legacy local runtime payloads when present; this path is not the active home for new mutable plugin state.

## Hermes-Orchestrator Integration

- Worker nodes mount standalone plugin roots directly when enabled.
- Legacy public/private plugin roots are mounted only when content is present.
- `horc` lifecycle and backup flows preserve node-local plugin caches and gitignored plugin state.
- Script feature modules under `/local/scripts` and plugin hooks here are designed to work together.

## Read Next

- [`discord-slash-commands/README.md`](discord-slash-commands/README.md)
- [`hermes-space-ui/README.md`](hermes-space-ui/README.md)
- [`exhaust/README.md`](exhaust/README.md)
- [`final-response-changed-files/README.md`](final-response-changed-files/README.md)
- [`../docs/features/plugins.md`](../docs/features/plugins.md)
