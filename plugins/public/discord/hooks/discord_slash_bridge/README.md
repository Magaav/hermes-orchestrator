# Discord Slash Bridge Runtime

This folder is the external command engine loaded by the Discord bootstrap patch.

## Files

- `runtime.py`: bootstrap runtime class loaded by `discord.py`
- `handlers.py`: concrete command handlers and shared helpers
- private `registry.yaml`: native overrides + bridge routing registry (`/local/plugins/private/discord/hooks/discord_slash_bridge/registry.yaml`)
- private `config.yaml`: quick alias/block map (`/local/plugins/private/discord/hooks/discord_slash_bridge/config.yaml`)

## Registry Quick Reference

`registry.yaml` supports two layers:

1. `native_overrides`
- for commands we want as native tree commands (`/restart`, `/metricas`, `/backup version`, `/model`)
- `/backup version` is orchestrator-only and now accepts:
  - `version` (optional label)
  - `node` (`orchestrator`, `colmeio`, `catatau`, `all`)
- backup flow:
  - local archive via clone manager under `/local/backups`
  - Drive mirror under `/backups/orchestrator/`

2. `slash_bridge`
- for commands registered in Discord payload but not in Hermes core
- supports:
  - `aliases`
  - `blocked`
  - `commands.<name>.dispatch`
  - `commands.<name>.handler`

Current custom handlers include:
- `custom:clean`
- `custom:pair`
- `custom:clone` (Dockerized Hermes node lifecycle via `/clone`)

## Add A New Command Quickly

Preferred workflow:

```bash
bash /local/plugins/public/discord/scripts/new_command_scaffold.sh \
  --name exemplo \
  --description "Meu novo comando" \
  --mode dispatch \
  --dispatch-target faltas \
  --acl-command faltas
```

Handler mode (creates `custom_handlers/<id>.py` and route `handler: custom:<id>`):

```bash
bash /local/plugins/public/discord/scripts/new_command_scaffold.sh \
  --name exemplo-custom \
  --mode handler \
  --handler-id exemplo_custom
```

Then run:

```bash
bash /local/plugins/public/discord/scripts/register_discord_commands.sh /local/plugins/private/discord/commands/<node>.json
bash /local/plugins/public/hermes-core/scripts/prestart_reapply.sh --strict
python3 /local/plugins/public/discord/scripts/verify_discord_customizations.py
```

Notes:

- Prefer one command name per handler (avoid alias duplicates).
- If no payload argument is provided, `register_discord_commands.sh` auto-resolves
  node payloads via `DISCORD_COMMANDS_FILE` or `NODE_NAME`.
