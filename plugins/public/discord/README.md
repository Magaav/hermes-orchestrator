# Discord Plugin

Public Discord plugin code lives here. Instance runtime/config state lives in `/local/plugins/private/discord`.

## Status

This tree is now deprecated as a runtime owner.

- Node startup and reapply flow must go through `/local/plugins/public/native/*`
- Legacy bridge/runtime files here are retained only as compatibility source
  material while the native plugins finish absorbing the remaining helpers
- Restart/update paths should not sync `hooks/discord_slash_bridge` back into
  `~/.hermes/hooks`

## Public (Tracked)

- `scripts/`
- `hooks/`
- `custom_handlers/`
- `tests/`
- templates:
  - `commands/*.json.example`
  - `discord_users.json.example`
  - `discord_webhooks_table.json.example`
  - `acl/node_acl.json.example`
  - `hooks/channel_acl/config.yaml.example`
  - `hooks/discord_slash_bridge/config.yaml.example`
  - `hooks/discord_slash_bridge/registry.yaml.example`
  - `models/node_models.json.example`

## Private (Local-Only)

- `/local/plugins/private/discord/commands/<node>.json`
- `/local/plugins/private/discord/discord_users.json`
- `/local/plugins/private/discord/discord_webhooks_table.json`
- `/local/plugins/private/discord/acl/<node>_acl.json`
- `/local/plugins/private/discord/models/<node>_models.json`
- `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
- `/local/plugins/private/discord/hooks/discord_slash_bridge/config.yaml`
- `/local/plugins/private/discord/hooks/discord_slash_bridge/registry.yaml`

## Path Contract

- Public root env: `HERMES_DISCORD_PLUGIN_DIR=/local/plugins/public/discord`
- Private root env: `HERMES_DISCORD_PRIVATE_DIR=/local/plugins/private/discord`
- Command/config loaders are hard-switched to private runtime paths with no legacy fallback.
- Role ACL sync script: `scripts/discord_role_acl_sync.py` (fail-closed slash ACL bootstrap/refresh).
- ACL contract validator: `scripts/discord_acl_contract_check.py` (role ACL + channel ACL + private models).
