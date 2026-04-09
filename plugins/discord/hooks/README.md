# Hooks - Hermes Gateway Customizations

This directory contains Discord customizations that survive `hermes-agent` updates.

## Production Strategy

Hermes core may be overwritten by updates, so custom behavior lives in `/local/plugins/discord` and is reapplied automatically by a prestart script.

## Single Bootstrap Architecture (Discord Slash)

Custom slash behavior uses one bootstrap patch + external runtime registry:

- Bootstrap patch script:
  - `/local/plugins/discord/scripts/reapply_discord_command_bootstrap.py`
- External runtime files (source of truth):
  - `/local/plugins/discord/hooks/discord_slash_bridge/runtime.py`
  - `/local/plugins/discord/hooks/discord_slash_bridge/handlers.py`
  - `/local/plugins/discord/hooks/discord_slash_bridge/registry.yaml`
  - `/local/plugins/discord/hooks/discord_slash_bridge/config.yaml`
- Runtime destination in Hermes home:
  - `~/.hermes/hooks/discord_slash_bridge/`

The bootstrap patches `gateway/platforms/discord.py` only to load this runtime.
Actual command logic stays external.

## What Bootstrap Runtime Does

1. Overrides native commands in one place:
- `/restart`
- `/metricas`
- `/backup version`

2. Bridges unknown slash commands (registered by payload JSON) using registry rules:
- aliases
- blocked commands
- handler-based routes
- generic dispatch routes

3. Enforces ACL via channel hook (`channel_acl`) for bridged/native commands.

## Adding Future Slash Commands

Use scaffold (recommended):

```bash
bash /local/plugins/discord/scripts/new_command_scaffold.sh \
  --name meu-comando \
  --description "Descrição do comando" \
  --mode dispatch \
  --dispatch-target faltas \
  --acl-command faltas
```

For custom logic file generation:

```bash
bash /local/plugins/discord/scripts/new_command_scaffold.sh \
  --name meu-comando-custom \
  --mode handler \
  --handler-id meu_comando_custom
```

Then:

1. Register command payload in Discord:
- `bash /local/plugins/discord/scripts/register_discord_commands.sh /local/plugins/discord/discord_commands.json`
2. Reapply + verify:
- `bash /local/plugins/discord/scripts/prestart_reapply.sh --strict`
- `python3 /local/plugins/discord/scripts/verify_discord_customizations.py`

No new per-command core patch script is needed.

## Channel ACL Hook

Channel behavior/model restrictions remain in:

- `/local/plugins/discord/hooks/channel_acl/config.yaml`
- `/local/plugins/discord/hooks/channel_acl/handler.py`

Threads inherit parent restrictions via `chat_id_alt`.

## Prestart Apply Chain

`/local/plugins/discord/scripts/prestart_reapply.sh` applies:

1. channel ACL patch/hooks
2. session info hook
3. thread parent context patch
4. guild sync patch
5. single Discord command bootstrap

## One-Command Update

Force sync Hermes + reapply + verify + restart:

```bash
bash /local/plugins/discord/scripts/update_hermes_force_sync_and_repatch.sh
```

## BOOT.md Auto-Reapply

`~/.hermes/BOOT.md` should run:

```bash
bash /local/plugins/discord/scripts/prestart_reapply.sh
```

## Debug

```bash
tail -f ~/.hermes/logs/gateway.log
python3 /local/plugins/discord/scripts/verify_discord_customizations.py
```
