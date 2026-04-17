# Update Engine (`horc update`)

## Overview

The update engine is now strict **test-then-apply**:

1. `horc update test`
2. `horc update apply all|node <csv>`

`apply` is hard-gated and will not mutate runtime state unless preflight succeeds and backup succeeds.

## Command Surface

```bash
horc update test [--source-branch <branch>] [--deprecate-plugins <p1,p2,...>]
horc update apply all [--source-branch <branch>] [--deprecate-plugins <p1,p2,...>]
horc update apply node <node1,node2,...> [--source-branch <branch>] [--deprecate-plugins <p1,p2,...>]
```

Legacy update commands are rejected:

- `horc agent update ...`
- `horc test update ...`
- `horc test-update`
- `horc update <node>`

## Lifecycle

### 1) `horc update test`

Preflight pipeline:

1. Refresh `/local/dummy/hermes-agent` from upstream (`--source-branch`).
2. Snapshot `/local/plugins -> /local/dummy/plugins` and `/local/scripts -> /local/dummy/scripts`.
3. Apply optional `--deprecate-plugins` only inside dummy snapshot.
4. Build fresh dummy node profile/bootstrap and run strict prestart reapply against dummy roots.
5. Emit report + plugin matrix artifacts.

### 2) `horc update apply ...`

Apply pipeline:

1. Resolve targets (`all` from env-backed nodes, or explicit CSV list).
2. Re-run full preflight (`update test`) with the same branch + deprecations.
3. Run `horc backup all` automatically; abort on backup failure.
4. Promote tested source `/local/dummy/hermes-agent -> /local/hermes-agent`.
5. Apply runtime plugin deprecations (`/local/plugins/public/<plugin> -> /local/plugins/public/deprecated/<plugin>`).
6. Roll out target nodes fail-fast:
   - sync node runtime from promoted source
   - restart node
   - stop immediately on first failure, report remaining nodes as pending

## Plugin Deprecation Flag

`--deprecate-plugins` accepts comma-separated plugin names under:

`/local/plugins/public/<name>`

Behavior:

- `update test`: deprecates only in dummy snapshot.
- `update apply`: deprecates in runtime root before node rollout.
- Move is idempotent and non-destructive (no deletion).
- Report fields include:
  - `deprecated_plugins_applied`
  - `deprecated_plugins_already_present`
  - `deprecated_plugins_missing`

Deprecated plugins are represented as `skipped_deprecated` in plugin matrix outputs.
Plugins already present under `plugins/public/deprecated/` are auto-detected and skipped in future tests even when `--deprecate-plugins` is omitted.

## Artifacts

Each run writes to:

- `/log/update/<run-id>/...`
- fallback: `/local/log/update/<run-id>/...` (when `/log/update` is unavailable)

Core files:

- `report.json`
- `plugin_matrix.json`
- `prestart.stdout.log`
- `prestart.stderr.log`
- `colmeio-prestart.log` (copied when available)

Plugin matrix statuses:

- `passed`
- `failed`
- `skipped_deprecated`

## Runbook

Recommended operator flow:

1. `horc update test --source-branch <branch> [--deprecate-plugins ...]`
2. Inspect `report.json` and `plugin_matrix.json`.
3. If green, run:
   - `horc update apply all ...`
   - or `horc update apply node <csv> ...`
4. On failure, use run artifacts to isolate failed plugin step or failed node and retry after fix.

## Failure Handling

- Preflight failure: no runtime mutations.
- Backup failure: no source promotion, no deprecation move, no rollout.
- Rollout failure: fail-fast, keep `updated_nodes` and `pending_nodes` in apply report for deterministic recovery.
