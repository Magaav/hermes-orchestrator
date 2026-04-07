# Hermes Agent Clone Runbook

## Scope
This document explains deterministic clone lifecycle operations for Hermes agents.

## Control Commands
### `/clone name:<agent>`
- Creates or starts an agent container from `/local/agents/<agent>.env`.
- Uses `CLONE_STATE` to decide seeding mode.

### `/reboot`
- Restarts the current container process (PID 1).
- On startup, prestart scripts reapply Discord hooks and env bootstrap.

## Failure Handling
### Permission Errors
- Symptom: `PermissionError` writing `/local/agents/<agent>/.hermes/config.yaml`.
- Resolution: normalize ownership recursively to host UID:GID before bootstrap.

### OpenViking Degraded Mode
- If OpenViking endpoint is unreachable, gateway starts in fail-open mode.
- Logs include endpoint and compatibility diagnostics.
