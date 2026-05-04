# Discord Slash Commands Plugin

`/local/plugins/discord-slash-commands` is the canonical host plugin root for
Discord slash UX in Hermes Orchestrator. Active bootstrap/runtime ownership
lives here.

## Ownership

- owns the active `pre_gateway_dispatch` governance runtime
- owns the active slash-command reconciler and bootstrap scripts
- owns the `global` and `custom` slash command catalogs
- owns `/status`, `/model`, `/acl`, `/slash`, `/clean`, `/faltas`, and `/metricas`

## Env Contract

- `PLUGIN_DISCORD_SLASH_COMMANDS=true|false`
- `PLUGIN_DISCORD_GOVERNANCE=true|false`
  deprecated migration alias; if this is true and slash is false, the canonical
  slash plugin still bootstraps

## Canonical Paths

- host plugin root: `/local/plugins/discord-slash-commands`
- node runtime cache:
  `/local/workspace/plugins/discord-slash-commands/cache`
- host-visible node cache:
  `/local/agents/nodes/<node>/workspace/plugins/discord-slash-commands/cache`

Cache layout:

```text
cache/
  catalogs/custom_commands.json
  governance/acl.json
  governance/models.json
  governance/channel_acl.yaml
  governance/discord_users.json
  state/node_activation.json
  state/app_scope.json
  migration.json
```

Notes:

- `node_activation.json` stores node intent for `custom` commands.
- `app_scope.json` stores the realized command state for a shared
  Discord app+guild pair.
- `colmeio` and `orchestrator` currently share the same app+guild, so
  `app_scope.json` is mirrored across those nodes.

## Namespace Model

- `global` and `custom` are namespaces on command definitions themselves.
- `global` commands are bundled with this plugin and are safe to distribute or
  upstream later.
- `custom` commands are deployment-specific and remain local to this repo/node
  cache even if the global layer is later upstreamed.
- Discord registration remains guild-scoped for all of them.

Initial `global` commands:

- `/status`
- `/model`
- `/acl`
- `/slash`
- `/clean`

Initial `custom` commands:

- `/faltas`
- `/metricas`

Defaults:

- `global` commands start enabled.
- `custom` commands start disabled on fresh nodes.
- migrated nodes preserve previously active `custom` commands.
- `/slash` is always enabled.

## Discord Reconciliation

The plugin reconciles guild commands from the canonical manifests/catalogs with
diff-based writes only:

- `PATCH` when a managed command payload differs
- `POST` when a managed command is missing
- `DELETE` when a plugin-owned managed command is disabled or stale
- never `PUT`

## Commands

### `/status`

What it does:

- shows current Hermes gateway session status for the node
- reports activity, tokens, and model-routing information
- respects channel-governed routing when the plugin override is enabled

How it behaves:

- `/status` uses the plugin override only when `/status` is enabled in `/slash`
- if disabled via `/slash command:status enable:false`, Hermes builtin
  `/status` takes over again
- `/status help` shows usage and override behavior

### `/model`

What it does:

- switches Hermes provider/model pairs from Discord using Hermes' native model runtime
- saves successful provider/model pairs into `cache/governance/models.json`

How it behaves:

- `/model name:deepseek-ai/deepseek-v4-pro provider:nvidia` switches the current session
- `/model list:configured` shows the plugin's saved catalog
- `/model list:available` shows authenticated provider catalogs
- `/model global:true ...` also persists the switch to `config.yaml`

### `/acl`

What it does:

- manages Discord command ACL and channel governance policy for the current node

How it behaves:

- `/acl help` shows usage
- `/acl command ...` updates `cache/governance/acl.json`
- `/acl channel ...` updates `cache/governance/channel_acl.yaml`
- model validation reads `cache/governance/models.json`

Examples:

- `/acl command command:metricas role:gerente`
- `/acl channel channel:123456 mode:specific model_key:nemotron120b allowed_commands:faltas always_allowed_commands:status default_action:skill:add free_text_policy:strict_item`
- `/acl channel channel:123456 mode:default`

### `/slash`

What it does:

- lists all `global` and `custom` commands available to the node
- enables or disables plugin-owned commands from Discord itself

How it behaves:

- `/slash` lists commands grouped by namespace
- `/slash help` explains namespace semantics and fallback behavior
- `/slash command:<name> enable:true|false` persists the new state and
  immediately reconciles Discord registration
- `/slash` itself cannot be disabled
- disabling `/status` removes only the plugin override and leaves Hermes builtin
  `/status` available

### `/clean`

What it does:

- deletes all deletable messages in the current Discord channel or thread
- reports deleted, failed, and undeletable counts back ephemerally

How it behaves:

- requires `/clean confirm:true`
- requires user `Administrator` or `Manage Messages`
- requires the bot to have `Manage Messages` in the channel/thread
- stays guild-scoped through the canonical command reconciler

### `/faltas`

What it does:

- manages Colmeio faltas lists through the existing faltas pipeline

How it behaves:

- loaded from the `custom` catalog
- only active on nodes where `/slash` enables it
- `/faltas help` shows structured usage for `listar`, `adicionar`, `remover`,
  and `limpar`

### `/metricas`

What it does:

- runs the existing Colmeio metrics dashboard flow

How it behaves:

- loaded from the `custom` catalog
- only active on nodes where `/slash` enables it
- `/metricas help` shows the supported `dias`, `formato`, and `skill` options

## Migration

On first bootstrap the plugin imports legacy shared Discord state from
`/local/plugins/private/discord/...` into the node-local cache:

- `commands/<node>.json` -> `catalogs/custom_commands.json`
- `acl/<node>_acl.json` -> `governance/acl.json`
- `models/<node>_models.json` -> `governance/models.json`
- bundled `channel_acl/config.yaml` -> `governance/channel_acl.yaml`
- `discord_users.json` -> `governance/discord_users.json`

Compatibility symlinks are created inside `cache/governance/` so the copied
legacy governance helpers keep working while the runtime is being completed.

## Development Notes

- the plugin keeps reusing the existing Colmeio metrics script and faltas
  pipeline script
- runtime help text comes from the canonical manifests/catalogs so README docs
  and `/status help` `/acl help` `/slash help` stay aligned
- `compat.py` remains a no-op diagnostics shim; no files are synced into
  `~/.hermes/hooks`
