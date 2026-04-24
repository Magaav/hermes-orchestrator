# `hermes-plugin-extension-points` Track

Status: `Proposal drafted`

## Summary

This track defines the minimum upstream Hermes Agent extension points needed to migrate our remaining legacy Orchestrator integrations into true Hermes-native plugins.

The goal is explicit:

- no patching `gateway/platforms/discord.py`
- no patching `gateway/run.py`
- no fake built-in plugin loader
- no `prestart_reapply.sh` dependency for migrated features
- only Hermes plugin APIs, hooks, slash commands, tools, CLI commands, and skills

## Repository Grounding

### What Hermes plugins can do today

From the current Hermes plugin surface:

- register tools via `ctx.register_tool(...)`
- register plugin hooks via `ctx.register_hook(...)`
- register slash commands routed by `gateway/run.py` via `ctx.register_command(...)`
- register CLI commands via `ctx.register_cli_command(...)`
- register skills via `ctx.register_skill(...)`

This is already enough for:

- tool-driven integrations
- CLI and gateway slash-command dispatch after a command already exists
- context injection before the LLM call
- tool/result observation and cleanup hooks

### What is still core-owned today

The remaining blockers are in the gateway and response-delivery path:

1. Discord app-command tree registration is built inside `gateway/platforms/discord.py`.
2. Discord interaction authorization/interception for app commands is core-owned.
3. Final assistant response rewriting before delivery is not exposed as a plugin hook.

Because of that, these remaining Orchestrator features cannot yet become true Hermes-native plugins without either:

- patching Hermes core, or
- upstreaming the missing extension points first

## Minimum Upstream API Proposal

### 1. Discord tree registration hook

Add a plugin-facing registration point so plugins can contribute real Discord app commands without patching `discord.py`.

Proposed surface:

```python
ctx.register_gateway_command(
    platform="discord",
    name="acl",
    description="Manage Discord governance rules",
    schema=...,
    handler=...,
    autocomplete=...,
)
```

Required behavior:

- Hermes core owns the Discord client and command tree
- plugins contribute command definitions through a stable API
- Discord-specific validation remains in core
- plugins do not call `tree.add_command(...)` directly
- plugin-registered gateway commands appear in sync with the normal Discord registration flow

Why this is needed:

- `discord-governance` needs `/acl`
- `discord-slash-commands` needs real Discord app commands, not only text slash dispatch after the fact

### 2. Gateway command authorization / interception hook

Add a plugin hook that can authorize, deny, or rewrite an incoming gateway command before Hermes handles it.

Proposed hook:

```python
ctx.register_hook("pre_gateway_command", callback)
```

Suggested callback contract:

```python
def callback(
    platform: str,
    command_name: str,
    raw_args: str,
    event: Any,
    source: Any,
    **kwargs,
) -> dict | None:
    ...
```

Allowed return values:

- `None`: no opinion, continue
- `{"decision": "allow"}`
- `{"decision": "deny", "message": "..."}`
- `{"decision": "rewrite", "command_name": "...", "raw_args": "..."}`
- `{"decision": "handled", "message": "..."}`

Required behavior:

- runs before normal gateway command dispatch
- errors are isolated like other plugin hooks
- denial can return a user-visible message cleanly
- works in Discord and other gateway platforms, even if only Discord uses it first

Why this is needed:

- `discord-governance` needs fail-closed ACL on slash commands
- future governance features may need per-platform allow/deny logic without patching the runner

### 3. Final response transform hook

Add a plugin hook that can transform the final assistant response immediately before delivery to CLI/gateway.

Proposed hook:

```python
ctx.register_hook("transform_final_response", callback)
```

Suggested callback contract:

```python
def callback(
    response_text: str,
    messages: list[dict],
    source: Any | None = None,
    session_id: str | None = None,
    **kwargs,
) -> str | dict | None:
    ...
```

Allowed return values:

- `None`: no change
- `str`: replacement response text
- `{"response_text": "...", "metadata": {...}}`

Required behavior:

- runs after the final assistant text is known
- runs before platform delivery
- has enough context to inspect tool history/messages
- supports deterministic response post-processing without patching `gateway/run.py`

Why this is needed:

- `final-response-changed-files` must append created/deleted/updated file sections to the delivered final response

### 4. Optional: gateway message event hook

If Hermes wants a cleaner separation, add a hook earlier than command dispatch:

```python
ctx.register_hook("pre_gateway_event", callback)
```

This is optional if `pre_gateway_command` is added and Hermes keeps command parsing in core.

## Plugin Mapping

### `discord-governance`

Needs:

- Discord tree registration hook
- gateway command authorization / interception hook

Scope unlocked by those hooks:

- `/acl command`
- `/acl channel`
- autocomplete on command/role/model/allowed lists
- fail-closed slash-command authorization
- channel/model governance without patching `discord.py`

Still local-only / not blocked:

- reading private ACL/model files
- role sync logic
- contract validation logic

### `discord-slash-commands`

Needs:

- Discord tree registration hook

Scope unlocked by that hook:

- plugin-owned Discord app command definitions
- native custom command registration without bootstrap patching
- session-policy behavior attached to those commands through normal plugin hooks/handlers

Still local-only / not blocked:

- handler logic
- command argument parsing
- CLI slash-command fallback behavior

### `wiki-engine`

Needs:

- no new Hermes extension point is strictly required for the first real native version

Reason:

- wiki bootstrap/query flows can live as tools, CLI commands, and `pre_llm_call` context helpers
- this track is blocked mainly by Orchestrator startup/distribution choices, not by Hermes plugin APIs

### `final-response-changed-files`

Needs:

- final response transform hook

Scope unlocked by that hook:

- append deterministic file footer to the delivered final response
- preserve the created / deleted / updated distinction
- avoid patching `gateway/run.py`

## Acceptance Criteria For Upstream Hermes

The extension-point work is sufficient when all of the following are true:

1. A plugin can register a real Discord app command without editing Hermes core.
2. A plugin can allow/deny/rewrite a gateway slash command before dispatch.
3. A plugin can rewrite the final delivered assistant response.
4. The hook/API contracts are documented in Hermes plugin docs.
5. The new APIs are covered by Hermes tests in both CLI and gateway-sensitive paths.

## Recommended Upstream PR Slices

### PR 1: Discord gateway command registration API

Deliver:

- core registry for plugin-contributed gateway commands
- Discord adapter consumption of that registry
- tests for registration and sync behavior

Unlocks:

- `discord-governance`
- `discord-slash-commands`

### PR 2: `pre_gateway_command` hook

Deliver:

- new plugin hook
- runner integration before normal command dispatch
- tests for allow / deny / handled / rewrite

Unlocks:

- `discord-governance`

### PR 3: `transform_final_response` hook

Deliver:

- new plugin hook
- runner/delivery integration before final send
- tests for response rewrite ordering and safety

Unlocks:

- `final-response-changed-files`

## Local Follow-Up After Upstreaming

Once the upstream APIs exist:

1. Rebuild `discord-governance` as a true Hermes plugin using only the new hooks and existing private contract files.
2. Rebuild `discord-slash-commands` on the Discord gateway registration API only.
3. Rebuild `final-response-changed-files` on `transform_final_response`.
4. Keep `wiki-engine` on the simpler native path using tools / CLI / pre-LLM hooks.
5. Delete the corresponding legacy patch steps from `prestart_reapply.sh`.

## Non-Goals

- Do not upstream Orchestrator-specific private file paths.
- Do not upstream node/env/bootstrap logic from this repo into Hermes core.
- Do not add plugin APIs that let plugins mutate Discord internals directly.
- Do not reintroduce ad hoc patch points disguised as plugin support.
