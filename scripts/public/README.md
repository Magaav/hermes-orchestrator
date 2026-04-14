# Scripts

Operational scripts used by Hermes Orchestrator.

Canonical script roots:
- public: `/local/scripts/public`
- private: `/local/scripts/private`

## Main Entry Points

- `clone/horc.sh`: primary CLI wrapper (`horc`).
- `clone/hord.sh`: compatibility alias for `horc`.
- `clone/clone.sh`: clone wrapper alias to `horc`.
- `clone/clone_manager.py`: deterministic lifecycle engine for start/stop/status/backup/restore/update.
- `ui-gateway/run.py`: local-only HTTP/SSE gateway for the experimental WASM UI (`WASM_UI_EXPERIMENTAL=1`).
- `install.sh`: repo install/bootstrap helper.
- `backup/backup_nodes_to_gdrive.sh`: compatibility wrapper to private backup entrypoint.
- `backup/restore_hermes_state.sh`: compatibility wrapper to private restore entrypoint.
- private canonical backup scripts: `/local/scripts/private/backup/*.sh`.

Log topology managed by `clone_manager.py`:
- `/local/logs/nodes/<node>/` for management/runtime/Hermes logs and node-scoped skill mirrors (`skills/`).
- `/local/logs/attention/nodes/<node>/` for warning+ mirrors (`warning-plus.log` + `hermes-errors.log` hardlinked mirror).

## OpenViking Tools

- `openviking/openviking_adapter.py`: thin adapter for commit/recall/context calls.
- `openviking/openviking_doctor.py`: production validation/diagnostics suite.

## Common Commands

```bash
horc start
horc status
horc restart
horc restart orchestrator
horc logs clean
horc backup all
horc backup node node1
horc restore /local/backups/<archive>.tar.gz
```

## Local State-Bound Setup

```bash
cp /local/state/orchestrator/backup_nodes_to_gdrive.env.example \
   /local/state/orchestrator/backup_nodes_to_gdrive.env
```
