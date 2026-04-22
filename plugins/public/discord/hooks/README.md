# Hooks - Hermes Gateway Customizations

This directory contains Discord customizations that survive `hermes-agent` updates.

## Production Strategy

Hermes core may be overwritten by updates, so custom behavior lives in `/local/plugins/public/discord` and is reapplied automatically by a prestart script.

## Discord Compatibility Runtime

Custom slash behavior now has two layers:

- legacy Hermes-core bootstrap patch script:
  - `/local/plugins/public/discord/scripts/reapply_discord_command_bootstrap.py`
- External runtime files (source of truth):
  - `/local/plugins/public/discord/hooks/discord_slash_bridge/runtime.py`
  - `/local/plugins/public/discord/hooks/discord_slash_bridge/handlers.py`
  - `/local/plugins/private/discord/hooks/discord_slash_bridge/registry.yaml`
  - `/local/plugins/private/discord/hooks/discord_slash_bridge/config.yaml`
- Runtime destination in Hermes home:
  - `~/.hermes/hooks/discord_slash_bridge/`

Preferred path for `/acl` and `/metricas`:

- the native plugins under `/local/plugins/public/native/{discord-governance,discord-slash-commands}`
- prestart syncs this runtime into `~/.hermes/hooks/...`
- command logic stays external and plugin-owned

The legacy bootstrap patcher still exists for older flows, but new node setups with the native Discord plugins enabled should rely on the plugin-owned runtime sync path instead of adding fresh core patches.

## What Bootstrap Runtime Does

1. Overrides native commands in one place:
- `/restart`
- `/metricas`
- `/backup version`
  - orchestrator-only
  - accepts `node` target (`orchestrator`, `colmeio`, `catatau`, `all`)
  - writes local archives to `/local/backups` and mirrors to `/backups/orchestrator/` on Drive

2. Bridges unknown slash commands (registered by payload JSON) using registry rules:
- aliases
- blocked commands
- handler-based routes
- generic dispatch routes

3. Enforces ACL via channel hook (`channel_acl`) for bridged/native commands.

## Adding Future Slash Commands

Use scaffold (recommended):

```bash
bash /local/plugins/public/discord/scripts/new_command_scaffold.sh \
  --name meu-comando \
  --description "Descrição do comando" \
  --mode dispatch \
  --dispatch-target faltas \
  --acl-command faltas
```

For custom logic file generation:

```bash
bash /local/plugins/public/discord/scripts/new_command_scaffold.sh \
  --name meu-comando-custom \
  --mode handler \
  --handler-id meu_comando_custom
```

Then:

1. Register command payload in Discord:
- `bash /local/plugins/public/discord/scripts/register_discord_commands.sh /local/plugins/private/discord/commands/<node>.json`
  If omitted, the script auto-resolves node payloads from `DISCORD_COMMANDS_FILE` or `NODE_NAME`.
2. Reapply + verify:
- `bash /local/plugins/public/hermes-core/scripts/prestart_reapply.sh --strict`
- `python3 /local/plugins/public/discord/scripts/verify_discord_customizations.py`

No new per-command core patch script is needed.

## Channel ACL Hook

Channel behavior/model restrictions remain in:

- `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
- `/local/plugins/public/discord/hooks/channel_acl/handler.py`

Threads inherit parent restrictions via `chat_id_alt`.

## Prestart Apply Chain

`/local/plugins/public/hermes-core/scripts/prestart_reapply.sh` applies:

1. channel ACL patch/hooks
2. session info hook
3. thread parent context patch
4. auto-thread-ignore-channels patch
5. guild sync patch
6. legacy Discord command bootstrap when native Discord plugins are not enabled
7. native Discord runtime sync when `PLUGIN_DISCORD_GOVERNANCE` and/or `PLUGIN_DISCORD_SLASH_COMMANDS` are enabled

## One-Command Update

Force sync Hermes + reapply + verify + restart:

```bash
bash /local/plugins/public/discord/scripts/update_hermes_force_sync_and_repatch.sh
```

## BOOT.md Auto-Reapply

`~/.hermes/BOOT.md` should run:

```bash
bash /local/plugins/public/hermes-core/scripts/prestart_reapply.sh
```

## Debug

```bash
tail -f ~/.hermes/logs/gateway.log
python3 /local/plugins/public/discord/scripts/verify_discord_customizations.py
```
