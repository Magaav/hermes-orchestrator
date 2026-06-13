# Public Scripts Context Contract

## Purpose

`scripts/public` owns git-tracked Hermes Orchestrator host automation and
reusable CLI/runtime helpers.

## Ownership

- Public scripts are reviewed source and may be mounted read-only into worker
  nodes.
- Deployment-local mutable entrypoints, credentials, and state belong under
  `/local/scripts/private`.
- Product UI/client code belongs under `/local/plugins`, especially
  `/local/plugins/wasm-agent`.

## Local Contracts

- Keep public scripts deterministic, auditable, and safe to version.
- Do not store secrets, host-local tokens, generated reports, or mutable
  deployment state here.
- Preserve stable `horc` workflows unless a migration note updates
  `docs/commands/horc.md` and the relevant README.
- Shared script changes can affect every node; keep blast radius explicit and
  rollback paths simple.

## Work Guidance

- Before editing lifecycle commands, read `README.md`, `clone/README.md`, and
  `docs/commands/horc.md`.
- Before editing guard automation, read `guard/README.md` and
  `docs/roadmap/guard/README.md`.
- Before editing backup/restore, read `backup/README.md` and keep private env
  examples out of secrets.

## Verification

- Prefer focused command smoke checks such as `horc status`, `horc build doctor`,
  or the script's own `--help`/doctor mode.
- For Python helpers, run the smallest relevant unit/smoke test if one exists.
- If a script changes node lifecycle behavior, verify against a non-production
  node or document why runtime verification was not run.

## Child Context Index

- `README.md`: public/private split, main entry points, and common commands.
- `clone/README.md`: `horc` wrapper and clone lifecycle engine.
- `guard/README.md`: host doctor loop.
- `backup/README.md`: backup/restore public wrappers.
- `openviking/README.md`: OpenViking helper scripts.
