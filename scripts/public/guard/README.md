# Guard Doctor Loop

Host-side doctor loop for Hermes Orchestrator.

## Run

```bash
python3 /local/scripts/public/guard/run.py
```

Single-cycle mode:

```bash
python3 /local/scripts/public/guard/run.py --once
```

## Environment

- `HERMES_GUARD_POLL_INTERVAL_SEC`
- `HERMES_GUARD_RESTART_COOLDOWN_SEC`
- `HERMES_GUARD_RETRY_CEILING`
- `HERMES_GUARD_STALL_TIMEOUT_SEC`
- `HERMES_GUARD_ATTENTION_WARN_THRESHOLD`
- `HERMES_GUARD_DISCORD_WEBHOOK_URL`
- `HERMES_GUARD_CLONE_MANAGER_SCRIPT`
- `HERMES_GUARD_LOG_ROOT`

## Logs

- Structured runs: `/local/logs/guard/runs.jsonl`
- Human summary: `/local/logs/guard/summary.log`
- Current snapshot: `/local/logs/guard/state.json`
- Activity dependency: `/local/logs/nodes/activities/<node>.jsonl`

## Scope

- Reads canonical node inventory from `/local/agents/registry.json` plus env/node roots.
- Evaluates runtime health from `clone_manager.py` status and canonical logs.
- Uses node activity timelines as an additional freshness signal.
- Applies bounded remediation via restart only.
- Writes no repo or node configuration changes.
