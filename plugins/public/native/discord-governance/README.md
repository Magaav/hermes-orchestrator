# Discord Governance Native Plugin

`discord-governance` now owns Discord ACL decisions and channel policy routing
through Hermes' supported `pre_gateway_dispatch` plugin hook plus the native
plugin command path.

## Env Contract

- `PLUGIN_DISCORD_GOVERNANCE=true|false`

## Current Private Contracts

- `/local/plugins/private/discord/acl/<node>_acl.json`
- `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
- `/local/plugins/private/discord/models/<node>_models.json`

## Current Behavior

- registers `/acl` through `ctx.register_command(...)`
- enforces Discord slash-command ACL during `pre_gateway_dispatch`
- normalizes or blocks restricted-channel free text before gateway dispatch
- applies channel model overrides and per-message channel prompt routing
- does not monkey-patch Hermes core files at runtime
- does not sync files into `~/.hermes/hooks/...`

## Notes

- the private-path contract is intentionally unchanged in this phase
- path resolution is centralized so we can move later to a plugin-owned
  private namespace with a smaller migration
