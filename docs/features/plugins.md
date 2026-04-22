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
- `PLUGIN_FINAL_RESPONSE_CHANGED_FILES`
- `PLUGIN_CANVA`
- `PLUGIN_BROWSER_PLUS`

The native plugin directories under `/local/plugins/public/native` now cover the upgrade-safer compatibility path for:

- `discord-governance` via plugin-owned sync of the Discord slash bridge and channel ACL runtime for `/acl`
- `discord-slash-commands` via plugin-owned sync of the Discord slash bridge runtime for `/metricas`

Current Discord shape:

- Hermes project plugins own the runtime sync and enable flags.
- The live Discord interaction/runtime logic is loaded from `~/.hermes/hooks/...`.
- New node starts no longer depend on adding fresh code into Hermes core for these two commands.

Future Hermes extension points are still desirable so this compatibility runtime can eventually become a pure upstream plugin API integration with no `prestart_reapply.sh` dependency.

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
