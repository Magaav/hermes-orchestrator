# Activity Timeline Feature

The activity timeline records one structured summary per agent interaction cycle.

## Canonical Path

- `/local/logs/nodes/activities/<node>.jsonl`

## Producer

The timeline is written by the built-in Hermes gateway hook:

- `hermes-agent/gateway/builtin_hooks/activity_timeline.py`

It runs on `agent:end`, so one completed, interrupted, waiting, or errored cycle produces one record.

## Why This Exists

- create an operator-readable timeline of what each node has been doing
- give Guard a recent interaction signal without inventing a second telemetry system
- let the UI render recent agent work directly from durable logs

## Record Shape

Each JSONL entry may include:

- `id`
- `ts`
- `node`
- `session_id`
- `agent_identity`
- `platform`
- `chat_type`
- `thread_id`
- `user_id`
- `user_name`
- `interaction_source`
- `cycle_outcome`
- `last_activity_desc`
- `message_preview`
- `response_preview`
- `tool_usage`
- `summary_text`

## Interaction Source

The built-in classifier emits:

- `human`
- `agent`
- `system`

## Outcome Values

- `completed`
- `interrupted`
- `errored`
- `waiting`

## Consumers

- Guard doctor loop
- UI gateway activity endpoint
- WASM UI agent timeline panel
