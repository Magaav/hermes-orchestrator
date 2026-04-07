# Discord Slash Bridge Runtime

This folder is the external command engine loaded by Discord bootstrap patch.

## Files

- `runtime.py`: bootstrap runtime class loaded by `discord.py`
- `handlers.py`: concrete command handlers and shared helpers
- `registry.yaml`: native overrides + bridge routing registry
- `config.yaml`: quick alias/block map

## Registry quick reference

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

## Add a new command quickly

Preferred workflow:

```bash
bash /local/workspace/discord/scripts/new_command_scaffold.sh \
  --name exemplo \
  --description "Meu novo comando" \
  --mode dispatch \
  --dispatch-target faltas \
  --acl-command faltas
```

Handler mode (creates `custom_handlers/<id>.py` and route `handler: custom:<id>`):

```bash
bash /local/workspace/discord/scripts/new_command_scaffold.sh \
  --name exemplo-custom \
  --mode handler \
  --handler-id exemplo_custom
```

Then run:

```bash
bash /local/workspace/discord/scripts/register_discord_commands.sh /local/workspace/discord/discord_commands.json
bash /local/workspace/discord/scripts/prestart_reapply.sh --strict
python3 /local/workspace/discord/scripts/verify_discord_customizations.py
```
