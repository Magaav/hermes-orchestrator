# Discord Plugin

Public Discord plugin code lives here. Instance runtime/config state lives in `/local/plugins/private/discord`.

## Public (Tracked)

- `scripts/`
- `hooks/`
- `custom_handlers/`
- `tests/`
- templates:
  - `commands/*.json.example`
  - `discord_users.json.example`
  - `discord_webhooks_table.json.example`
  - `hooks/channel_acl/config.yaml.example`
  - `hooks/discord_channel_routing_hook/config.yaml.example`
  - `hooks/discord_slash_bridge/config.yaml.example`
  - `hooks/discord_slash_bridge/registry.yaml.example`

## Private (Local-Only)

- `/local/plugins/private/discord/commands/<node>.json`
- `/local/plugins/private/discord/discord_users.json`
- `/local/plugins/private/discord/discord_webhooks_table.json`
- `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
- `/local/plugins/private/discord/hooks/discord_channel_routing_hook/config.yaml`
- `/local/plugins/private/discord/hooks/discord_slash_bridge/config.yaml`
- `/local/plugins/private/discord/hooks/discord_slash_bridge/registry.yaml`

## Path Contract

- Public root env: `HERMES_DISCORD_PLUGIN_DIR=/local/plugins/public/discord`
- Private root env: `HERMES_DISCORD_PRIVATE_DIR=/local/plugins/private/discord`
- Command/config loaders are hard-switched to private runtime paths with no legacy fallback.
