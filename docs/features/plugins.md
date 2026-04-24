# Plugins Feature

The plugins feature is the extensibility and runtime integration layer of Hermes Orchestrator.

## Canonical Roots

- Public plugins: `/local/plugins/public`
- Private plugins: `/local/plugins/private`

## Why It Is Segregated

- Public plugins hold reusable hook/runtime code and remain fully versioned.
- Private plugins hold mutable runtime payloads, memory/wiki data, and deployment-local command/config state.

## How Hermes-Orchestrator Uses It

- Prestart patch pipeline executes from `/local/plugins/public/hermes-core/scripts/prestart_reapply.sh`.
- Discord bridge/runtime integrations live in `/local/plugins/public/discord`.
- Native Hermes project-plugin ports live in `/local/plugins/public/native`.
- Node command payloads and private Discord state are stored under `/local/plugins/private/discord`.
- Shared wiki runtime lives under `/local/plugins/private/wiki`.

## Native Migration Surface

The staged native migration now packages feature ownership under `/local/plugins/public/native` and enables it per node from `/local/agents/envs/<node>.env`.

Current native migration flags:

- `PLUGIN_DISCORD_GOVERNANCE`
- `PLUGIN_DISCORD_SLASH_COMMANDS`
- `PLUGIN_WIKI_ENGINE`
- `PLUGIN_FINAL_RESPONSE_FILES_CHANGED`
- `PLUGIN_CANVA`
- `PLUGIN_BROWSER_PLUS`

The native plugin directories under `/local/plugins/public/native` now cover the Hermes-native path for:

- `discord-governance` via official Hermes hooks for `/acl`, slash-command ACL, and channel routing
- `discord-slash-commands` via official Hermes plugin command registration for `/metricas`

Current Discord shape:

- Hermes project plugins own the enable flags and project-plugin sync into `./.hermes/plugins/<name>`.
- The live Discord governance and slash-command behavior runs from Hermes-native plugin registration and hooks.
- Discord-enabled nodes no longer depend on `~/.hermes/hooks/discord_slash_bridge` or `~/.hermes/hooks/channel_acl`.

Future cleanup still remains:

- move private Discord data from the shared `/local/plugins/private/discord/...` tree into plugin-owned namespaces
- replace the remaining legacy helper imports inside the native plugins with fully self-contained plugin modules

## Discord Role ACL

Discord slash authorization is split by plugin layer contract:

- Public engine and bootstrap script:
  - `/local/plugins/public/discord/hooks/discord_slash_bridge/role_acl.py`
  - `/local/plugins/public/discord/scripts/discord_role_acl_sync.py`
- Private per-node ACL policy:
  - `/local/plugins/private/discord/acl/<node>_acl.json`
  - `/local/plugins/private/discord/hooks/channel_acl/config.yaml`
  - `/local/plugins/private/discord/models/<node>_models.json`

The ACL is fail-closed:

- Any slash command missing from `commands.<name>.min_role` is denied.
- `@everyone` can be used for low-risk commands.
- Higher hierarchy roles inherit lower-role command permissions.

## Synergy With Other Modules

- Scripts in `/local/scripts/public` orchestrate plugin startup, lifecycle, and backup flows.
- `horc` backup/restore keeps private plugin runtime state restorable across VM rebuilds.
- Worker nodes consume public/private plugin mounts according to orchestrator topology.

## Related Docs

- [`../../plugins/README.md`](../../plugins/README.md)
- [`scripts.md`](scripts.md)
- [`../commands/horc.md`](../commands/horc.md)
- [`../commands/discord-role-acl.md`](../commands/discord-role-acl.md)
- [`../commands/discord-acl-workflow.md`](../commands/discord-acl-workflow.md)
