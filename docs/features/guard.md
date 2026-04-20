# Guard Feature

`guard` is the host-side doctor loop for Hermes Orchestrator.

## Entry Point

- `/local/scripts/public/guard/run.py`

## Purpose

- watch registered nodes continuously
- detect unhealthy, stalled, or repeatedly failing runtimes
- log every decision locally
- send high-signal Discord alerts
- apply only bounded restart remediation

## Safety Boundaries

- restart only
- no delete, reset, or config mutation
- cooldown enforced per node
- retry ceiling enforced per node
- every decision is written to canonical logs

## Canonical Logs

- `/local/logs/guard/runs.jsonl`
- `/local/logs/guard/summary.log`
- `/local/logs/guard/state.json`

## Configuration

- `HERMES_GUARD_POLL_INTERVAL_SEC`
- `HERMES_GUARD_RESTART_COOLDOWN_SEC`
- `HERMES_GUARD_RETRY_CEILING`
- `HERMES_GUARD_STALL_TIMEOUT_SEC`
- `HERMES_GUARD_ATTENTION_WARN_THRESHOLD`
- `HERMES_GUARD_DISCORD_WEBHOOK_URL`
- `HERMES_GUARD_CLONE_MANAGER_SCRIPT`
- `HERMES_GUARD_PYTHON_BIN`
- `HERMES_GUARD_LOG_ROOT`

## Decisions

Per node, each cycle resolves to one of:

- `healthy`
- `warned`
- `skipped`
- `restarted`
- `restart-failed`
- `cooldown-active`
- `retry-exhausted`

## Dependencies

Guard reads from:

- `/local/agents/registry.json`
- `/local/agents/envs/*.env`
- `/local/agents/nodes/*`
- `scripts/public/clone/clone_manager.py`
- `/local/logs/nodes/<node>/*`
- `/local/logs/attention/nodes/<node>/*`
- `/local/logs/nodes/activities/<node>.jsonl`
