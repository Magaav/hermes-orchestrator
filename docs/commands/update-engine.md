# Safe Node Update Runbook

`horc update` now has one canonical operator workflow. Older multi-step manual update flows are retired from operator use.

## Standard Flow

Update one production node at a time:

1. Start a guided run:

```bash
horc update run <prod-node> --stage <stage-node> [--source-branch <branch>] [--deprecate-plugins p1,p2,...]
```

What this does:
- refreshes and validates the Hermes source against the dummy preflight snapshot
- refreshes the stage node from production
- stops the production node first when the stage is expected to share Discord credentials
- updates only the stage node
- stops at `stage validation required`

2. Validate the stage node manually in Discord.

3. Record the stage approval:

```bash
horc update validate <run-id> --phase stage
```

What this does:
- promotes the validated source into the production node rollout
- stops the stage node first when stage and prod share Discord credentials
- updates only the production node
- stops at `prod validation required`

4. Validate production manually in Discord.

5. Close the run:

```bash
horc update validate <run-id> --phase prod
```

6. Only after the run is complete, start a new run for the next node.

## Status and Recovery

Inspect a guided run:

```bash
horc update status <run-id>
```

Resume a failed run:

```bash
horc update resume <run-id>
```

The updater persists checkpoints and the exact next safe command in the run report, so recovery should come from `status` and `resume`, not from ad hoc manual steps.

Checkpoint meanings:
- `stage_validation_pending`: stage is updated and waiting for manual validation
- `prod_validation_pending`: production is updated and waiting for manual validation
- `completed`: the node rollout is finished
- `stage_prepare_failed`, `stage_rollout_failed`, `prod_rollout_failed`: resume is allowed

## Artifacts

All update artifacts now live only under:

```text
/local/logs/update/<run-id>/
```

Core files:
- `report.json`
- `plugin_matrix.json` for nested preflight/apply runs when available
- `prestart.stdout.log`
- `prestart.stderr.log`
- `colmeio-prestart.log` when copied from strict preflight

Historical mistaken update roots may still exist from older runs, but new automation must write only to `/local/logs/update`.

## Failure Rules

- Preflight failure: no stage or production rollout should continue
- Stage rollout failure: fix the issue, then `horc update resume <run-id>`
- Production rollout failure: do not start another node; fix or resume the same run
- Shared Discord credentials: never leave stage and production running at the same time

## Migration Notes

Retired operator paths:
- legacy profile-clone flows
- legacy test/apply update flows

If older update artifacts still exist outside `/local/logs/update`, keep them only as historical records or move/archive them manually. New automation must read and write `/local/logs/update`.
