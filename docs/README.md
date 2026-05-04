# Documentation

`/local/docs` contains versioned Hermes Orchestrator documentation.

## What Belongs Here

- `agents/`: node environment and runtime contract docs.
- `commands/`: command references and operational workflows.
- `features/`: current feature documentation.
- `roadmap/`: larger roadmap tracks, proposals, future work, and continuity notes.
- `assets/`: documentation assets such as images.

## Documentation Truth

Current-behavior docs must match the software as it exists now. Future intent
belongs in roadmap or proposal sections and must be labeled as such. When code
and docs disagree, inspect the current codeflow and update docs to reflect
reality before moving on.

Any code CRUD change that affects behavior, paths, commands, APIs, plugins,
or operational workflow must include a docs-sync check.
