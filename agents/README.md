# Agents

`/local/agents` stores node profiles and node runtime roots.

## Structure

- `envs/<node>.env`: node profile (secrets + node-level toggles)
- `envs/node.env.example`: single template for every node
- `nodes/<node>/`: generated runtime state (not versioned)
- logs are centralized under `/local/logs/nodes/<node>/` (including `skills/` mirrors) and warning+ mirrors under `/local/logs/attention/nodes/<node>/`

## Env Contract

Use lean node profiles. Keep only values that differ from defaults.

Primary keys:

- `NODE_AGENT_DEFAULT_MODEL_PROVIDER`
- `NODE_AGENT_DEFAULT_MODEL`
- `NODE_AGENT_FALLBACK_MODEL_PROVIDER`
- `NODE_AGENT_FALLBACK_MODEL`
- `NODE_AGENT_ALLOWED_COMMANDS`
- `NODE_STATE`
- `NODE_STATE_FROM_BACKUP_PATH`
- `OPENVIKING_ENABLED`
- `OPENVIKING_ENDPOINT`
- `CAMOFOX_ENABLED`
- `CAMOFOX_URL`
- `DISCORD_HOME_CHANNEL`

Defaults handled automatically by orchestrator:

- `NODE_NAME` inferred from `<node>.env` filename
- node paths (`HERMES_NODE_ROOT`, `HERMES_HOME`, `HERMES_DATA_DIR`) derived from standard topology
- `COLMEIO_LOGS_DIR` defaults to `/local/logs/nodes/<node>` so skill mirrors stay node-scoped
- `OPENVIKING_ACCOUNT` and `OPENVIKING_USER` default to node name when omitted
- Discord restart/reboot commands and delays are runtime defaults (set explicitly only when custom)
- legacy keys remain backward-compatible (`CLONE_*`, `MEMORY_OPENVIKING`, `BROWSER_CAMOFOX`)

## New Node Quickstart

1. Copy `envs/node.env.example` to `envs/<node>.env`.
2. Fill secrets and node-specific values.
3. Start with `horc start <node>`.
