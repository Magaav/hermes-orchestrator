# Discord Slash Bridge Runtime

This folder is the external command engine loaded by the Discord bootstrap patch.

## Files

- `runtime.py`: bootstrap runtime class loaded by `discord.py`
- `handlers.py`: concrete command handlers and shared helpers
- `registry.yaml`: native overrides + bridge routing registry
- `config.yaml`: quick alias/block map

## Registry Quick Reference

`registry.yaml` supports two layers:

1. `native_overrides`
- for commands we want as native tree commands (`/restart`, `/metricas`, `/backup version`, `/model`)

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
bash /local/plugins/discord/scripts/new_command_scaffold.sh \
  --name exemplo \
  --description "Meu novo comando" \
  --mode dispatch \
  --dispatch-target faltas \
  --acl-command faltas
```

Handler mode (creates `custom_handlers/<id>.py` and route `handler: custom:<id>`):

```bash
bash /local/plugins/discord/scripts/new_command_scaffold.sh \
  --name exemplo-custom \
  --mode handler \
  --handler-id exemplo_custom
```

Then run:

```bash
bash /local/plugins/discord/scripts/register_discord_commands.sh /local/plugins/discord/discord_commands.json
bash /local/plugins/discord/scripts/prestart_reapply.sh --strict
python3 /local/plugins/discord/scripts/verify_discord_customizations.py
```
