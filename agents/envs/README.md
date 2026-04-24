# Agents Envs

`/local/agents/envs/` stores the environment files used by the agents in this project.

This directory is the source of truth for:

- node profiles in `envs/<node>.env`
- the orchestrator profile in `envs/orchestrator.env`
- versioned templates such as `node.env.example` and `orchestrator.env.example`

Each `<node>.env` file defines how one node boots, which model/provider it uses, which optional features are enabled, and which runtime behavior flags apply to that node.

Keep real `.env` files machine-local and secret. Only templates and documentation should be committed here.

## Files

- `README.md`: explains the purpose of this directory and the env contract
- `node.env.example`: example worker-node profile
- `orchestrator.env.example`: example orchestrator profile
- `<node>.env`: real node profile, local only, not versioned
- `orchestrator.env`: real orchestrator profile, local only, not versioned

## Naming Standard

This README uses the current naming standard for the project:

- plugin toggles should use the `PLUGIN_*` prefix
- Hermes-agent env related should be kept unchanged using its same var name, exemple `HERMES_YOLO_MODE`
- when a legacy key still exists in runtime code, that legacy key is called out explicitly

## Node Variables

This section is the direct reference for `/local/agents/envs/<node>.env`.

### Mandatory

These are the core variables every node profile should define explicitly.

| Variable | Type | Expects | Default when missing | Notes |
|---|---|---|---|---|
| `NODE_STATE` | `int` | `1`, `2`, `3`, or `4` | `1` | Bootstrap mode. If `3`, `NODE_STATE_FROM_BACKUP_PATH` becomes required. |
| `NODE_AGENT_DEFAULT_MODEL_PROVIDER` | `string` | provider id such as `minimax` | none | Default provider for the node. |
| `NODE_AGENT_DEFAULT_MODEL` | `string` | model id or model label | none | Default model for the node. |

### Optional

These variables are not mandatory for every node, but they are part of the supported node contract.

| Variable | Type | Expects | Default when missing | Notes |
|---|---|---|---|---|
| `NODE_AGENT_FALLBACK_MODEL_PROVIDER` | `string` | provider id | none | Fallback provider when the default path is unavailable. |
| `NODE_AGENT_FALLBACK_MODEL` | `string` | model id or model label | none | Fallback model paired with the fallback provider. |
| `NODE_AGENT_FOLLOWUP_ELAPSED` | `int` | elapsed time threshold, for example `10` | runtime-defined | Follow-up timing window. |
| `NODE_AGENT_FOLLOWUP_SUMMARY` | `bool` | `true` or `false` | runtime-defined | Enables follow-up summary behavior. |
| `NODE_AGENT_FINALRESPONSE_ENFORCE_FILES_CHANGED` | `bool` | `true` or `false` | runtime-defined | Enforces changed-files reporting in final responses. |
| `NODE_STATE_FROM_BACKUP_PATH` | `string` | filesystem path | empty string | Required when `NODE_STATE=3`. |
| `NODE_RESEED` | `bool` | `true` or `false` | `false` | One-shot runtime refresh flag. Reset to `false` after successful reseed. |
| `NODE_TIME_ZONE` | `string` | IANA timezone such as `UTC` or `America/Sao_Paulo` | `UTC` | When omitted, this README treats `UTC` as the contract default. |
| `NODE_SST_MODEL` | `string` | local STT model id such as `large-v3-turbo` | `large-v3-turbo` | Present in orchestrator example comments. |
| `NODE_SST_LANGUAGE` | `string` | language code such as `en` or `pt` | `en` | Present in orchestrator example comments. |
| `HERMES_YOLO_MODE` | `bool` | `1`, `true`, or other truthy value | disabled | Canonical approval-bypass variable. |
| `DISCORD_HOME_CHANNEL` | `string` | Discord channel id | none | Default home channel for the node. |
| `DISCORD_APP_ID` | `string` | Discord application id | none | Discord transport configuration. |
| `DISCORD_SERVER_ID` | `string` | Discord server id | none | Preferred guild/server id key. |
| `DISCORD_GUILD_ID` | `string` | Discord guild id | none | Alternate guild id key used by some flows. |
| `DISCORD_BOT_TOKEN` | `string` | bot token | none | Required for Discord transport. |
| `DISCORD_DISABLE_SKILL_SLASH_COMMANDS` | `bool` | `true` or `false` | runtime-defined | Disables skill slash-command registration. |
| `DISCORD_ALLOWED_USERS` | `csv string` | comma-separated Discord user ids | open allowlist | Recommended for access control. |
| `DISCORD_REQUIRE_MENTION` | `bool` | `true` or `false` | runtime-defined | Global mention-gating flag. |
| `DISCORD_REQUIRE_MENTION_CHANNELS` | `csv string` | comma-separated channel ids | unset | When present, becomes the authoritative mention-gating list. |
| `DISCORD_FREE_RESPONSE_CHANNELS` | `csv string` | comma-separated channel ids | unset | Channels that bypass mention requirement. |
| `DISCORD_IGNORED_CHANNELS` | `csv string` | comma-separated channel ids | unset | Channels ignored by the bot. |
| `DISCORD_AUTO_THREAD` | `bool` | `true` or `false` | runtime-defined | Enables thread-first responses. |
| `DISCORD_AUTO_THREAD_IGNORE_CHANNELS` | `csv string` | comma-separated channel ids | unset | Channels excluded from auto-thread behavior. |
| `DISCORD_ROLE_ACL_SAFE_COMMANDS` | `csv string` | command names such as `status,help,usage,provider` | `status,help,usage,provider` | Still used by `/local/plugins/public/discord/scripts/discord_role_acl_sync.py` to define slash commands that remain allowed under ACL-safe mode. Documented in `/local/docs/agents/node.env.md`. |
| `DISCORD_ROLE_ACL_FALLBACK_HIERARCHY` | `csv string` | role names in priority order | unset | Still used by `/local/plugins/public/discord/scripts/discord_role_acl_sync.py` as a role-name fallback when live role fetch is unavailable. Documented in `/local/docs/agents/node.env.md`. |
| `NVIDIA_API_KEY` | `string` | API key | none | NVIDIA provider credential. |
| `OPENROUTER_API_KEY` | `string` | API key | none | OpenRouter credential. |
| `MINIMAX_API_KEY` | `string` | API key | none | MiniMax credential. |
| `MINIMAX_GROUP_ID` | `string` | group id | none | MiniMax group identifier. |
| `GOOGLE_EMAIL_LOGIN` | `string` | email address | unset | Optional Google login. |
| `GOOGLE_OAuth_CLIENT_ID` | `string` | OAuth client id | none | Optional Google OAuth credential. |
| `GOOGLE_OAuth_CLIENT_SECRET` | `string` | OAuth client secret | none | Optional Google OAuth credential. |
| `GOOGLE_OAuth_REFRESH_TOKEN` | `string` | OAuth refresh token | none | Optional Google OAuth credential. |

### Plugins

All plugin toggles and their direct dependent variables live under this subsection.

| Variable | Type | Expects | Default when missing | Notes |
|---|---|---|---|---|
| `PLUGIN_CANVA` | `bool` | `true` or `false` | `false` | Enables the native Canva plugin. |
| `CANVA_REFRESH_TOKEN` | `string` | refresh token | none | Required when `PLUGIN_CANVA=true`. |
| `CANVA_CLIENT_ID` | `string` | client id | none | Required when `PLUGIN_CANVA=true`. |
| `CANVA_CLIENT_SECRET` | `string` | client secret | none | Required when `PLUGIN_CANVA=true`. |
| `PLUGIN_BROWSER_PLUS` | `bool` | `true` or `false` | `false` | Enables the Browser Plus plugin. |
| `BROWSER_USE_API_KEY` | `string` | API key | unset | Optional Browser Use cloud credential for Browser Plus helpers. |
| `PLUGIN_DISCORD_GOVERNANCE` | `bool` | `true` or `false` | `false` | Enables the native Discord governance plugin. |
| `PLUGIN_DISCORD_SLASH_COMMANDS` | `bool` | `true` or `false` | `false` | Enables the native Discord slash-commands plugin. |
| `PLUGIN_WIKI` | `bool` | `true` or `false` | `false` | New canonical wiki flag for project docs. Runtime still contains legacy `NODE_WIKI_ENABLED` references and native `PLUGIN_WIKI_ENGINE` references. |
| `PLUGIN_WIKI_ENGINE` | `bool` | `true` or `false` | `false` | Current native runtime key still present in bootstrap/plugin docs. Treat as legacy-to-be-converged toward `PLUGIN_WIKI`. |
| `PLUGIN_FINAL_RESPONSE_FILES_CHANGED` | `bool` | `true` or `false` | `false` | Enables the changed-files footer plugin. |
| `PLUGIN_OPENVIKING` | `bool` | `true` or `false` | `false` | Canonical naming target only. Runtime currently still reads legacy `OPENVIKING_ENABLED`, and the feature is not fully implemented yet. |
| `OPENVIKING_ENDPOINT` | `string` | URL | unset | OpenViking endpoint. |
| `OPENVIKING_ACCOUNT` | `string` | account name | node name | Optional account override. |
| `OPENVIKING_USER` | `string` | user name | node name | Optional user override. |
| `PLUGIN_CAMOFOX` | `bool` | `true` or `false` | `false` | Canonical naming target for pattern consistency. Feature is deprecated. Runtime currently still reads legacy `CAMOFOX_ENABLED`. |
| `CAMOFOX_URL` | `string` | URL | unset | Camofox endpoint. |

## Notes

- `NODE_NAME` is inferred from the `<node>.env` filename and does not need to be set manually.
- `PLUGIN_WIKI`, `PLUGIN_OPENVIKING`, and `PLUGIN_CAMOFOX` are the naming standard presented by this README, but not every one of those names is fully implemented as a runtime env alias yet.
- Some optional variables become operationally required when their related feature is enabled. Example: if `PLUGIN_CANVA=true`, Canva credentials must also be present.

For detailed bootstrap behavior and Discord mention-routing rules, see `/local/docs/agents/node.env.md`.
