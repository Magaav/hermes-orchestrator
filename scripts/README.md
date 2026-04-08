# Scripts

Operational scripts used by Hermes Orchestrator.

## Main Entry Points

- `clone/horc.sh`: primary CLI wrapper (`horc`).
- `clone/hord.sh`: compatibility alias for `horc`.
- `clone/clone.sh`: clone wrapper alias to `horc`.
- `clone/clone_manager.py`: deterministic lifecycle engine for start/stop/status/backup/restore/update.
- `install.sh`: repo install/bootstrap helper.

## OpenViking Tools

- `openviking/openviking_adapter.py`: thin adapter for commit/recall/context calls.
- `openviking/openviking_doctor.py`: production validation/diagnostics suite.

## Common Commands

```bash
horc start
horc status
horc backup all
horc backup node colmeio
horc restore /local/backups/<archive>.tar.gz
```
