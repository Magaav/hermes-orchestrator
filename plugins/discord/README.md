# Discord Hub

Canonical home for Colmeio Discord integration artifacts.

## Canonical paths

- `discord_commands.json` -> `/local/workspace/discord/discord_commands.json`
- `discord_users.json` -> `/local/workspace/discord/discord_users.json`
- `discord_webhooks_table.json` -> `/local/workspace/discord/discord_webhooks_table.json`
- `discord_users.json.example` (tracked template) -> `/local/plugins/discord/discord_users.json.example`
- `discord_webhooks_table.json.example` (tracked template) -> `/local/plugins/discord/discord_webhooks_table.json.example`
- Scripts -> `/local/workspace/discord/scripts/`
- Hooks -> `/local/workspace/discord/hooks/`
- Cron launchers -> `/local/workspace/crons/`

## Strict Mode

Legacy compatibility symlinks were intentionally removed.
Use only the canonical paths above.
Runtime `discord_users.json` is node-local state and is intentionally not versioned.
Runtime `discord_webhooks_table.json` is node-local state and is intentionally not versioned.

## One-Command Upgrade

Use this command to sync Hermes from `main` and reapply all Colmeio Discord patches:

```bash
bash /local/workspace/discord/scripts/update_hermes_force_sync_and_repatch.sh
```

## Slash command architecture (current)

Custom slash behavior is now managed by a **single bootstrap patch** plus
external runtime files (not per-command patch scripts):

- Bootstrap patch:
  - `/local/workspace/discord/scripts/reapply_discord_command_bootstrap.py`
- Runtime/registry:
  - `/local/workspace/discord/hooks/discord_slash_bridge/runtime.py`
  - `/local/workspace/discord/hooks/discord_slash_bridge/handlers.py`
  - `/local/workspace/discord/hooks/discord_slash_bridge/registry.yaml`
  - `/local/workspace/discord/hooks/discord_slash_bridge/config.yaml`

For new slash commands:

1. run scaffold script to create payload + registry route:
   - `bash /local/workspace/discord/scripts/new_command_scaffold.sh --name meu-comando --mode dispatch --dispatch-target faltas --acl-command faltas`
2. register payload (`register_discord_commands.sh`)
3. run `prestart_reapply.sh --strict` + verify script
