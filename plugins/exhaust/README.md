# Exhaust Plugin

`exhaust` is a Hermes-Agent plugin for structured capability exhaustion.

`/exhaust` is not "try harder". It means: before Hermes declares failure, it
must inspect the available capability surface and attempt distinct safe recovery
paths within a bounded budget.

## What It Adds

- `/exhaust <task>` command
- `/bruteforce <task>` alias
- `exhaust_inventory` tool for capability inventory
- Passive recovery hints on failed tool results, when enabled
- Logs under `/local/logs/nodes/<node>/plugins/exhaust.log`

The plugin is disabled by default. It does nothing unless this env var is true:

```bash
PLUGINS_EXHAUST=true
```

## Enable Per Node

Add this to `/local/agents/envs/<node>.env`:

```bash
PLUGINS_EXHAUST=true
```

Then sync/enable the project plugin for that node:

```bash
python /local/plugins/exhaust/scripts/exhaust_env_bootstrap.py \
  --env-file /local/agents/envs/<node>.env

horc restart <node>
```

The bootstrap helper:

- syncs `/local/plugins/exhaust` into the node's `.hermes/plugins/exhaust`
- sets `HERMES_ENABLE_PROJECT_PLUGINS=true`
- ensures `exhaust` is present in Hermes `config.yaml` `plugins.enabled`

Runtime still checks `PLUGINS_EXHAUST=true`, so stale config alone cannot
activate behavior if the node env disables it.

## Usage

```text
/exhaust fix the failing CI job and open a PR
/bruteforce migrate this workflow without touching Hermes core
```

The command rewrites the task into an agent turn with this protocol:

1. Detect the blocker.
2. Inventory tools, skills, plugins, commands, scripts, docs, wiki/memory, and routes.
3. Build a fallback graph.
4. Try distinct fallback classes.
5. Stop only on success, safety/policy boundary, missing required input, missing credentials, or budget exhaustion.
6. Report the attempt ledger and remaining blocker.

## Configuration

Optional env vars:

```bash
PLUGINS_EXHAUST_MAX_ATTEMPTS=4
PLUGINS_EXHAUST_MAX_SECONDS=900
PLUGINS_EXHAUST_MAX_TOOL_NUDGES=3
PLUGINS_EXHAUST_PASSIVE=true
HERMES_EXHAUST_BROWSER_CDP_URL=http://127.0.0.1:9222
```

Passive mode uses the official `transform_tool_result` hook to attach bounded
recovery hints to failed tool results. It does not retry tools by itself and it
does not bypass Hermes permissions.

For web tasks where normal cloud egress can be blocked, such as YouTube,
`HERMES_EXHAUST_BROWSER_CDP_URL` makes `/exhaust` treat a user Chrome CDP
reverse tunnel as a first-class route. The prompt and `exhaust_inventory`
surface the verification URL and `/browser connect <url>` command before the
agent declares the browser path blocked.

## Guardrails

- bounded attempt budget
- bounded passive tool-result nudges
- no infinite retry loops
- no destructive retry unless explicitly authorized and materially changed
- no credential guessing
- no permission bypass
- respects existing Hermes safety and policy behavior

## Available Hermes Hooks Used

- `ctx.register_command(...)`
- `ctx.register_tool(...)`
- `pre_gateway_dispatch`
- `pre_llm_call`
- `post_tool_call`
- `transform_tool_result`
- `on_session_end`

## Current Limitations

The current Hermes plugin interface is enough for explicit `/exhaust` behavior
and passive failed-tool nudges, but not enough to fully enforce recovery.

Missing or partial upstream surfaces:

- A final-response transform or pre-finalization hook that can intercept "I give up" before delivery.
- A first-class agent-turn command API for plugin commands in gateway mode. This plugin uses `pre_gateway_dispatch` rewrite as the safe available route.
- A retry-controller API that lets a plugin enforce distinct fallback attempts and budget limits inside the agent loop.
- A current-turn enabled-capability API. `exhaust_inventory` can inspect registered capabilities, but cannot always prove which toolsets were enabled for the active turn.

Clean upstream shape:

- `pre_final_response` or `transform_final_response` with messages, tool history, final text, and session id.
- `ctx.enqueue_agent_turn(...)` for plugin commands across CLI and gateway.
- A structured recovery controller hook that can request one more model turn with a plugin-supplied recovery prompt and a bounded budget.

Until those exist, `exhaust` stays compatible by using prompt/context injection,
tool-result hints, and command rewrite only.
