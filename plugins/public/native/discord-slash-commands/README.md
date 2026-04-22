# Discord Slash Commands Native Plugin

`discord-slash-commands` is the Hermes-native home for the Discord slash
command bridge and the session-policy behavior that rides with it.

## Env Contract

- `PLUGIN_DISCORD_SLASH_COMMANDS=true|false`

`PLUGIN_DISCORD_SLASH_COMMANDS=true` is the intended enable flag for this
package.

## Current Status

This package now owns the Discord slash-command compatibility runtime from the
plugin side:

- syncs the Discord slash-bridge runtime into `~/.hermes/hooks/discord_slash_bridge/`
- keeps `/metricas` on the Discord-native compatibility path instead of the
  generic Hermes plugin-command path
- runs the legacy metrics dashboard script through the external bridge runtime
- is applied during node prestart by `scripts/apply_discord_slash_commands_runtime.py`

Current limitation:

- this still depends on Hermes builds that already expose the external
  Discord hook runtime loader; it no longer adds new core patches itself
