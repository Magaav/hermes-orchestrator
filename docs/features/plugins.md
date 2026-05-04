# Plugins Feature

The plugins feature is the extensibility and runtime integration layer of Hermes Orchestrator.

## Canonical Roots

- Canonical standalone host plugins:
  `/local/plugins/discord-slash-commands`,
  `/local/plugins/exhaust`,
  `/local/plugins/final-response-changed-files`,
  `/local/plugins/hermes-space-ui`
- `hermes-space-ui` local runtime state: `/local/plugins/hermes-space-ui/state`

## Why It Is Segregated

- Standalone plugin roots hold reusable hook/runtime code and remain fully versioned.
- Mutable runtime state lives in node-local plugin caches or gitignored plugin state directories.
- Compatibility/migration inputs are allowed only when a plugin documents them;
  new active plugin ownership should use standalone package roots plus
  package-named node-local caches.

## How Hermes-Orchestrator Uses It

- Canonical Discord slash runtime ownership now lives in `/local/plugins/discord-slash-commands`.
- Mutable Discord slash/governance state for that plugin now lives per node under `/local/workspace/plugins/discord-slash-commands/cache`.
- `hermes-space-ui` keeps its local Space Agent checkout, customware, logs, and task state under `/local/plugins/hermes-space-ui/state` instead of `/local/plugins/private/hermes-space-ui`.
- Shared wiki runtime lives under `/local/wiki`.

## Plugin Enable Flags

Current plugin enable flags still present in node env files and bootstrap code:

- `PLUGIN_DISCORD_GOVERNANCE`
- `PLUGIN_DISCORD_SLASH_COMMANDS`
- `PLUGIN_WIKI_ENGINE`
- `PLUGIN_FINAL_RESPONSE_FILES_CHANGED`
- `PLUGIN_CANVA`
- `PLUGIN_BROWSER_PLUS`

`PLUGIN_DISCORD_GOVERNANCE` is deprecated and only kept as a migration alias
for the canonical slash plugin bootstrap.

Active Discord slash ownership lives in the standalone plugin package:

- `discord-slash-commands` now owns `/status`, `/acl`, `/slash`, `/faltas`, `/metricas`, slash reconciliation, and governance routing from `/local/plugins/discord-slash-commands`
- `discord-governance` remains as deprecated legacy reference code and is no longer part of the active bootstrap chain

Current Discord shape:

- Hermes project plugins own the enable flags and project-plugin sync into `./.hermes/plugins/<name>`.
- The live Discord governance and slash-command behavior runs from the canonical `discord-slash-commands` plugin package.
- Discord-enabled nodes no longer depend on `~/.hermes/hooks/discord_slash_bridge` or `~/.hermes/hooks/channel_acl`.
- Slash command state is node-local under `workspace/plugins/discord-slash-commands/cache`, with mirrored `app_scope.json` when multiple nodes share the same Discord app+guild.

Future cleanup still remains:

- remove the remaining legacy governance helper imports still reused inside the canonical slash plugin
- complete the migration away from compatibility symlinks once native governance helpers are fully in-plugin

## Discord Role ACL

Discord slash authorization is split by plugin layer contract:

- Canonical engine and bootstrap package:
  - `/local/plugins/discord-slash-commands/runtime.py`
  - `/local/plugins/discord-slash-commands/scripts/register_guild_plugin_commands.py`
- Node-local ACL policy for the canonical slash plugin:
  - `/local/workspace/plugins/discord-slash-commands/cache/governance/acl.json`
  - `/local/workspace/plugins/discord-slash-commands/cache/governance/channel_acl.yaml`
  - `/local/workspace/plugins/discord-slash-commands/cache/governance/models.json`

The ACL is fail-closed:

- Any slash command missing from `commands.<name>.min_role` is denied.
- `@everyone` can be used for low-risk commands.
- Higher hierarchy roles inherit lower-role command permissions.

## Discord Slash Namespaces

- `global` and `custom` are namespaces on slash command definitions, not on plugins and not on Discord API scope.
- `global` commands are bundled with `discord-slash-commands` and default-enabled.
- `custom` commands are deployment-specific and enabled per node via `/slash`.
- Discord writes remain guild-scoped and diff-based: `PATCH`, `POST`, `DELETE`, never `PUT`.

## Synergy With Other Modules

- Scripts in `/local/scripts/public` orchestrate plugin startup, lifecycle, and backup flows.
- `horc` backup/restore keeps node-local plugin caches and documented gitignored
  plugin state restorable across VM rebuilds.
- Worker nodes consume standalone plugin packages and node-local caches
  according to orchestrator topology.

## Related Docs

- [`../../plugins/README.md`](../../plugins/README.md)
- [`scripts.md`](scripts.md)
- [`../commands/horc.md`](../commands/horc.md)
- [`../commands/discord-role-acl.md`](../commands/discord-role-acl.md)
- [`../commands/discord-acl-workflow.md`](../commands/discord-acl-workflow.md)
