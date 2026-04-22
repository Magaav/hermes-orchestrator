# Discord Governance Native Plugin

`discord-governance` is the Hermes-native packaging for the Discord ACL and
channel-governance surface that was previously owned only by the legacy
`/local/plugins/public/discord` injection stack.

## Env Contract

- `PLUGIN_DISCORD_GOVERNANCE=true|false`

`PLUGIN_DISCORD_GOVERNANCE=true` is the intended enable flag for this package.

The first migration pass keeps the existing node-private contract files:

- `/local/plugins/private/discord/acl/<node>_acl.json`
- `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
- `/local/plugins/private/discord/models/<node>_models.json`

## Current Status

This package now owns the Discord governance compatibility runtime from the
plugin side:

- syncs the Discord slash-bridge runtime into `~/.hermes/hooks/discord_slash_bridge/`
- syncs the channel ACL runtime into `~/.hermes/hooks/channel_acl/`
- keeps `/acl` on the Discord-native compatibility path instead of the generic
  Hermes plugin-command path
- is applied during node prestart by `scripts/apply_discord_governance_runtime.py`

Current limitation:

- this still depends on Hermes builds that already expose the external
  Discord hook runtime loader; it no longer adds new core patches itself
