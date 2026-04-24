# Discord Slash Commands Native Plugin

`discord-slash-commands` now registers Discord-visible slash commands through
the official Hermes plugin command interface.

## Env Contract

- `PLUGIN_DISCORD_SLASH_COMMANDS=true|false`

## Current Behavior

- registers `/metricas` through `ctx.register_command(...)`
- registers `/faltas` through `ctx.register_command(...)`
- registers `/discord-slash-status` for node-local registration diagnostics
- captures Discord request context during `pre_gateway_dispatch`
- reconstructs handler arguments from Discord interaction options when needed
- keeps Hermes' built-in Discord slash registration authoritative instead of
  patching the live Discord adapter in memory
- lets Hermes' built-in global slash sync continue to publish the generic
  plugin command entries Hermes knows how to auto-register
- uses `scripts/register_guild_plugin_commands.py` during prestart to patch or
  create guild-scoped overlays for the plugin-owned commands without deleting
  global commands
- keeps `/metricas` and `/faltas` visible with structured Discord options like
  `dias`, `formato`, `action`, and `loja` instead of collapsing everything
  into a single `args` field
- works whether `DISCORD_COMMAND_SYNC_POLICY` is `safe`, `bulk`, or `off`
- uses the current private Discord contracts as inputs
- does not sync files into `~/.hermes/hooks/...`
- keeps a no-op compatibility shim only for diagnostics/tests

## Notes

- the metrics dashboard still reuses the existing Colmeio metrics script
- the faltas command reuses the existing faltas pipeline script
- private-path resolution is centralized so we can migrate later to a
  plugin-owned private namespace without another broad refactor
