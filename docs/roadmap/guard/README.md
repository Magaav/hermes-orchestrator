# `guard` Track

Status: `V1 implemented` (bounded rollout)

## Summary

`guard` is the host-side doctor loop for Hermes Orchestrator. It continuously inspects registered nodes, writes auditable decisions to canonical logs, sends Discord alerts for important incidents, and applies only bounded restart remediation.

This track is no longer exploratory. V1 establishes the operational contract that future Guard work should extend rather than replace.

## V1 Scope

- Long-lived daemon at `/local/scripts/public/guard/run.py`
- Canonical fleet discovery from:
  - `/local/agents/registry.json`
  - `/local/agents/envs/*.env`
  - `/local/agents/nodes/*`
- Runtime evaluation from:
  - `scripts/public/clone/clone_manager.py status`
  - canonical node logs under `/local/logs/nodes/`
  - attention mirrors under `/local/logs/attention/nodes/`
  - per-node activity logs under `/local/logs/nodes/activities/`
- Safe remediation only:
  - notify-first evaluation on every incident
  - restart-only automated remediation
  - no config mutation, agent reset, delete, or destructive repair

## Canonical Logs

Guard writes to `/local/logs/guard/`:

- `runs.jsonl`: append-only structured decision log per node per cycle
- `summary.log`: human-readable rolling operator summary
- `state.json`: latest daemon snapshot used by the UI and monitor surfaces

Structured run records include:

- `ts`
- `cycle_id`
- `node`
- `symptoms`
- `decision`
- `remediation_action`
- `remediation_result`
- `retry_count`
- `retry_ceiling`
- `cooldown_until`

## Decision Model

Per cycle, each node resolves to one of:

- `healthy`
- `warned`
- `skipped`
- `restarted`
- `restart-failed`
- `cooldown-active`
- `retry-exhausted`

The intent is to keep Guard auditable and predictable. Any future remediation class should fit this same decision-first model.

## Alerting

Discord alert routing is included in V1 through `HERMES_GUARD_DISCORD_WEBHOOK_URL`.

Guard currently emits alerts for:

- unhealthy node with no remediation taken
- remediation started
- remediation failed
- retry ceiling reached

Alert payloads are intentionally compact and stable so the same event shape can be mirrored in the UI without a second translation layer.

## Safety Boundaries

- No unbounded restart behavior
- Cooldown enforced per node
- Retry ceiling enforced per node
- Notify-first behavior on ambiguous failures
- Every automated decision must be recoverable from local logs

## Activity Timeline Dependency

Guard now depends on the node activity timeline as a first-class health signal.

Canonical path:

- `/local/logs/nodes/activities/<node>.jsonl`

Each record is one structured summary per interaction cycle, not one record per tool call. This gives Guard and the UI a durable timeline of recent operator, agent, and system interactions.

## Next Steps

1. Expand health heuristics with more Hermes-specific failure signals while preserving restart-only remediation by default.
2. Add quarantine/escalation policy for nodes that repeatedly oscillate between `restarted` and `restart-failed`.
3. Introduce richer incident correlation between Guard runs, attention logs, and timeline cycles.
4. Add optional operator controls to acknowledge or suppress specific Guard alerts from the UI.
