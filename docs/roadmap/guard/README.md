# `guard` Track

Exploration track for continuous background monitoring and bounded operational remediation.

## Objective

Detect unhealthy runtime patterns early, route high-signal alerts, and apply limited, auditable remediation actions.

## Focus Areas

- Background process monitoring for orchestrator and worker nodes.
- Watch patterns (restart loops, process exits, stale runtime behavior, critical log spikes).
- Canonical `/local/logs/` routing with emphasis on attention-level signals.
- Real-time Discord alerting for high-priority operational events.
- Bounded remediation (small, safe, reversible actions only).

## Monitoring Surfaces

- `/local/logs/nodes/<node>/management.log`
- `/local/logs/nodes/<node>/runtime.log`
- `/local/logs/nodes/<node>/hermes/errors.log`
- `/local/logs/attention/nodes/<node>/warning-plus.log`
- `/local/logs/attention/nodes/<node>/hermes-errors.log`

## Guardrails

- No unbounded restart behavior.
- Enforce cooldowns and retry ceilings.
- Keep every automated action traceable via logs.
- Prefer notify-first behavior for ambiguous failures.

## Milestones

1. Define baseline watch patterns and severity model.
2. Implement alert routing and throttling policy.
3. Introduce bounded remediation handlers with rollback-aware checks.
4. Validate behavior against synthetic failure scenarios.

## Status

`Exploring`.
