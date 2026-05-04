# Git Hooks

`/local/.githooks` contains repository-local Git hooks for Hermes Orchestrator.

## Current Hook

- `pre-commit`: blocks common runtime, secret, and generated-state paths from
  being committed, then scans staged additions for high-risk token patterns.

## Change Rules

Hook changes affect every contributor who enables the repo hook path. Keep them
small, shell-portable, and aligned with `.gitignore`, `README.md`, and
`SECURITY.md`.

If the runtime-state allowlist changes, update the root documentation in the
same change so commit rules and docs stay in sync.
