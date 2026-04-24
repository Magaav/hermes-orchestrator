# Agents

`/local/agents` stores node profiles and node runtime roots.

## Structure

- `envs/README.md`: documentation for the env directory and node variable reference
- `envs/<node>.env`: node profile (secrets + node-level toggles)
- `envs/orchestrator.env.example`: host orchestrator template
- `envs/node.env.example`: worker node template
- `nodes/<node>/`: generated runtime state (not versioned)
- `nodes/<node>/scripts/{public,private}`: host-visible mirrors of `/local/scripts/{public,private}`
- `nodes/<node>/plugins/{public,private}`: worker mount anchors to `/local/plugins/{public,private}`
- `nodes/<node>/cron`: mountpoint from `/local/crons/<node>`
- `/local/datas/<node>`: centralized private node data root (mounted in runtime as `/local/data`)
- logs are centralized under `/local/logs/nodes/<node>/` and `/local/logs/attention/nodes/<node>/`

Canonical shared roots now live outside `agents/`:

- `/local/scripts/public`
- `/local/scripts/private`
- `/local/plugins/public`
- `/local/plugins/private`
- `/local/skills`
- `/local/datas`

## Env Contract

Use lean node profiles. Keep only values that differ from defaults.

For strict bootstrap requirements and mention-routing controls, see:
- `/local/agents/envs/README.md`
- `/local/docs/agents/node.env.md`

Core keys:

- `NODE_AGENT_DEFAULT_MODEL_PROVIDER`
- `NODE_AGENT_DEFAULT_MODEL`
- `NODE_AGENT_FALLBACK_MODEL_PROVIDER`
- `NODE_AGENT_FALLBACK_MODEL`
- `NODE_RESEED`
- `HERMES_YOLO_MODE` (optional, `1` to bypass command approvals)
- `NODE_STATE`
- `NODE_STATE_FROM_BACKUP_PATH`
- `NODE_TIME_ZONE` (IANA timezone, for example `America/Sao_Paulo`)
- `DISCORD_HOME_CHANNEL`

Plugins and plugin-owned settings:

- `PLUGIN_WIKI` (default `false`; current runtime still has legacy `NODE_WIKI_ENABLED` and `PLUGIN_WIKI_ENGINE` references)
- `PLUGIN_OPENVIKING` (default `false`; current runtime still reads legacy `OPENVIKING_ENABLED`)
- `OPENVIKING_ENDPOINT`
- `PLUGIN_CAMOFOX` (default `false`; current runtime still reads legacy `CAMOFOX_ENABLED`)
- `CAMOFOX_URL`
- `PLUGIN_CANVA`
- `CANVA_REFRESH_TOKEN`
- `CANVA_CLIENT_ID`
- `CANVA_CLIENT_SECRET`
- `PLUGIN_BROWSER_PLUS`
- `PLUGIN_DISCORD_GOVERNANCE`
- `PLUGIN_DISCORD_SLASH_COMMANDS`
- `PLUGIN_WIKI_ENGINE` (legacy runtime/native plugin key still present today)
- `PLUGIN_FINAL_RESPONSE_FILES_CHANGED`

Discord note:
- `PLUGIN_DISCORD_GOVERNANCE` and `PLUGIN_DISCORD_SLASH_COMMANDS` now sync plugin-owned compatibility runtimes into `nodes/<node>/.hermes/hooks/...` so `/acl` and `/metricas` survive Hermes upgrades without adding new core patches.

Defaults handled automatically by orchestrator:

- `NODE_NAME` inferred from `<node>.env` filename
- `NODE_RESEED=false` when omitted; set `NODE_RESEED=true` for a one-shot runtime reseed from `/local/hermes-agent`
- `NODE_TIME_ZONE` is injected as `HERMES_TIMEZONE` (and `TZ`) at runtime
- node paths (`HERMES_NODE_ROOT`, `HERMES_HOME`, `HERMES_DATA_DIR`) derived from standard topology
- `COLMEIO_LOGS_DIR` defaults to `/local/logs/nodes/<node>`
- `HERMES_WIKI_ROOT` resolves to `/local/wiki` inside worker containers and `/local/agents/nodes/<node>/wiki` on host
- `OPENVIKING_ACCOUNT` and `OPENVIKING_USER` default to node name when omitted
- Discord restart/reboot commands and delays are runtime defaults (set explicitly only when custom)

## Quickstart

1. Orchestrator profile: copy `envs/orchestrator.env.example` to `envs/orchestrator.env`, or run `horc start` and let it auto-create on first run.
2. Worker profile: copy `envs/node.env.example` to `envs/<node>.env`.
3. Fill secrets and node-specific values.
4. Start with `horc start` (orchestrator) and `horc start <node>` (workers).

## Update behavior

- `horc update all` refreshes `/local/hermes-agent`, reseeds every node, and reconciles `/local/agents/registry.json`.
- `horc update node <name>` refreshes `/local/hermes-agent`, reseeds only the named node, and leaves others untouched.
- Reseeds preserve node-local `.hermes` state and automatically reset `NODE_RESEED=false` after success.
