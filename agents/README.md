# Agents

`/local/agents` stores node profiles and node runtime roots.

## Structure

- `envs/<node>.env`: node profile (secrets + node-level toggles)
- `envs/orchestrator.env.example`: host orchestrator template
- `envs/node.env.example`: worker node template
- `nodes/<node>/`: generated runtime state (not versioned)
- `nodes/<node>/scripts/{public,private}`: host-visible mirrors of `/local/scripts/{public,private}`
- `nodes/<node>/plugins/{public,private}`: worker mount anchors to `/local/plugins/{public,private}`
- `nodes/<node>/cron`: mountpoint from `/local/crons/<node>`
- `nodes/<node>/data`: node-local mutable runtime data (canonical)
- logs are centralized under `/local/logs/nodes/<node>/` and `/local/logs/attention/nodes/<node>/`

Canonical shared roots now live outside `agents/`:

- `/local/scripts/public`
- `/local/scripts/private`
- `/local/plugins/public`
- `/local/plugins/private`
- `/local/skills`

## Env Contract

Use lean node profiles. Keep only values that differ from defaults.

Primary keys:

- `NODE_AGENT_DEFAULT_MODEL_PROVIDER`
- `NODE_AGENT_DEFAULT_MODEL`
- `NODE_AGENT_FALLBACK_MODEL_PROVIDER`
- `NODE_AGENT_FALLBACK_MODEL`
- `HERMES_YOLO_MODE` (optional, `1` to bypass command approvals)
- `NODE_STATE`
- `NODE_STATE_FROM_BACKUP_PATH`
- `NODE_WIKI_ENABLED`
- `OPENVIKING_ENABLED`
- `OPENVIKING_ENDPOINT`
- `CAMOFOX_ENABLED`
- `CAMOFOX_URL`
- `DISCORD_HOME_CHANNEL`

Defaults handled automatically by orchestrator:

- `NODE_NAME` inferred from `<node>.env` filename
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
