# Hermes Space UI State

This folder contains local generated runtime state for `/local/plugins/hermes-space-ui`.

## Current Contents

- `space-agent/`: generated upstream Space Agent checkout used by `horc space start`.
- `space-customware/`: generated writable Space Agent customware root. Hermes modules are synced here under `L1` and user spaces/configuration under `L2`.
- `node/`: local Node runtime downloaded or prepared by startup scripts when needed.
- bridge logs, pid files, task state, and other local mutable files may also appear here.

## Editing Rules

- Do not edit nested generated/upstream contents to satisfy documentation coverage.
- Do not treat `space-agent/` as the canonical source for Hermes product changes. Space Agent changes should be modules/customware first, or generic upstreamable seams when core changes are unavoidable.
- Do not commit runtime state from this folder. Only this parent README and `.gitignore` are intended to be versioned.

For current integration behavior, read `/local/plugins/hermes-space-ui/README.md` and `/local/docs/roadmap/space-os/README.md`.
