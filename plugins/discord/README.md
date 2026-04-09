# Discord Hub

Canonical home for Discord integration artifacts used by orchestrator nodes.

## Canonical Paths

- `discord_commands.json` -> `/local/plugins/discord/discord_commands.json`
- `discord_users.json` (runtime, not tracked) -> `/local/plugins/discord/discord_users.json`
- `discord_webhooks_table.json` (runtime, not tracked) -> `/local/plugins/discord/discord_webhooks_table.json`
- `discord_users.json.example` (tracked template) -> `/local/plugins/discord/discord_users.json.example`
- `discord_webhooks_table.json.example` (tracked template) -> `/local/plugins/discord/discord_webhooks_table.json.example`
- Scripts -> `/local/plugins/discord/scripts/`
- Hooks -> `/local/plugins/discord/hooks/`
- Node cron launchers -> `/local/crons/<node>/`

Legacy `/local/workspace/discord/*` compatibility fallbacks may still exist in some scripts, but `/local/plugins/discord/*` is the source of truth.

## Strict Mode

Runtime `discord_users.json` and `discord_webhooks_table.json` are intentionally not versioned.

## One-Command Upgrade

Use this command to sync Hermes from `main` and reapply Discord customizations:

```bash
bash /local/plugins/discord/scripts/update_hermes_force_sync_and_repatch.sh
```

## Slash Command Architecture

Custom slash behavior is managed by a single bootstrap patch plus external runtime files:

- Bootstrap patch:
  - `/local/plugins/discord/scripts/reapply_discord_command_bootstrap.py`
- Runtime/registry:
  - `/local/plugins/discord/hooks/discord_slash_bridge/runtime.py`
  - `/local/plugins/discord/hooks/discord_slash_bridge/handlers.py`
  - `/local/plugins/discord/hooks/discord_slash_bridge/registry.yaml`
  - `/local/plugins/discord/hooks/discord_slash_bridge/config.yaml`

For new slash commands:

1. Run scaffold script to create payload + registry route:
   - `bash /local/plugins/discord/scripts/new_command_scaffold.sh --name meu-comando --mode dispatch --dispatch-target faltas --acl-command faltas`
2. Register payload (`register_discord_commands.sh`)
3. Run `prestart_reapply.sh --strict` + verify script
