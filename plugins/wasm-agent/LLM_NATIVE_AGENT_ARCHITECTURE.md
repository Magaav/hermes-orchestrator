# LLM-Native wasm-agent Architecture

This is the target architecture for avatar-chat, embedded agent routing, Hermes
dispatch, context budgeting, and per-turn proof.

For the implementation track, critique loop, acceptance gates, and frontier
prompt, read `LLM_NATIVE_AGENT_MANIFEST_PLAN.md`.

## Goal

Build a cheap, strong, autonomous wasm-agent.

Cheap means the default path uses deterministic routing, compact state, local
indexes, bounded lookup tools, and strict token budgets before any large model
loop. A simple UI edit must not burn hundreds of thousands of tokens searching
the wrong roots.

Strong means the agent understands product ownership and proof contracts before
acting. It should know that avatar-chat UI belongs to `plugins/wasm-agent`,
native shell work belongs to `native/`, generated runtime state is not source,
and Hermes node work is a separate runtime boundary.

Autonomous means the user should not need to provide file paths, repeat
workspace roots, babysit model direction, or ask Codex to watch and repair
every run. The system should route, scope, execute, verify, and report cost
from its own protocol.

LLM-native means the agent gets explicit compact contracts, not a human UI dump
or vague prose. It should operate from stable fields, route ids, capability
reports, action schemas, budgets, counters, and proof handles.

## Non-Goal

Do not build wasm-agent by adding more product strings to `static_server.py` or
similar runtime files. A list of CSS selectors, DOM classes, feature labels, or
one-off regexes is not a map. It is reactive monkey-patching.

Do not use Hermes as the planner of last resort for product routing. Hermes is
currently expensive, redundant, and weak at ownership inference. It may provide
skills, tools, bridge execution, and model reasoning inside a bounded contract;
it must not discover the product map by broad search.

## Architecture

The correct flow is:

```text
user turn
  -> intent/surface classifier
  -> route contract resolver
  -> cheap deterministic lookup/proof
  -> bounded plan
  -> skill/bridge execution only if needed
  -> watcher proof
  -> exact token/cost report
  -> harvest repeated uncertainty into contracts
```

The wrong flow is:

```text
user turn
  -> direct head guesses
  -> Hermes broad-searches arbitrary roots
  -> no matches
  -> add another string to server code
```

## Route Contract Registry

Routing ownership must be declarative and testable. The registry can begin as a
small machine-readable file, but it must not live as ad hoc code branches.

Minimum route contract:

```json
{
  "route_id": "wasm-agent.avatar-chat.ui",
  "surface": "avatar-chat",
  "owner": "plugins/wasm-agent",
  "workspace_root": "/local/plugins/wasm-agent",
  "allowed_write_roots": ["/local/plugins/wasm-agent"],
  "likely_paths": ["public/styles.css", "public/app.js"],
  "caps": ["repo.read", "repo.edit", "proof.report", "test.run"],
  "cheap_checks": [
    "rg route symbols inside workspace_root",
    "read route index if available",
    "fail route_contract_missing before broad external search"
  ],
  "proof": ["changed files", "focused static check", "token usage total"],
  "token_budget": {
    "head_max": 3000,
    "bridge_max": 50000,
    "api_call_max": 8
  }
}
```

Route contracts should support:

- owner and workspace root
- allowed read/write roots
- likely paths and local indexes
- capabilities and forbidden actions
- deterministic preflight checks
- proof requirements
- token/API-call/time budgets
- escalation policy when the route is missing

If route resolution fails, the correct result is `route_contract_missing` with
the missing field. It is not acceptable to dispatch a model to search
`/local/agents`, `/home/ubuntu`, or unrelated roots.

## Agent Turn Protocol

The direct head should receive a compact envelope like:

```text
ENV wa-turn-v1
OBJ <user objective>
SUR avatar-chat
ROUTE wasm-agent.avatar-chat.ui
ROOT /local/plugins/wasm-agent
CAP repo.read repo.edit proof.report
BUD head=3000 bridge=50000 calls=8
LOOKUP route.files route.symbols route.tests
PROOF changed_files token_usage route_id
```

The model may ask for detail through lookup handles. It should not receive full
logs, screenshots, raw UI dumps, or broad nested JSON by default.

## Hermes Role

Hermes is a skill and bridge provider.

Allowed:

- execute a bounded task under `workspace_root`
- call named tools exposed by wasm-agent
- use a provided skill with a declared input/output schema
- return compact proof and exact token usage

Forbidden:

- infer workspace ownership from raw user text
- broad-search outside `allowed_write_roots`
- continue after `api_call_max`, `bridge_max`, or repeated no-progress signals
- report "no matches" without proving the declared route root was searched
- decide product architecture or update route ownership ad hoc

If Hermes needs a capability that is not in the contract, it must return
`capability_missing`. If it lacks a workspace root, it must return
`route_contract_missing`.

## Cheapness Rules

1. Resolve route before model dispatch.
2. Run the cheapest deterministic check before broad search.
3. Prefer local indexes and `rg` in the declared workspace root.
4. Stop on repeated no-progress tool loops.
5. Keep token accounting exact and per turn.
6. Separate context-window pressure from provider token billing.
7. Cache route maps and symbol indexes by file hash.
8. Harvest repeated misses into route contracts or harness promises.

## Token Accounting

Every turn must expose:

- `token_usage_total`
- `token_usage_components.head`
- `token_usage_components.bridge`
- input tokens
- output tokens
- cached input tokens
- API call count
- model names
- route id
- workspace root

For product decisions, the most important cost is per-question total. For
optimization, the important split is head versus bridge. A small direct-head
call plus a large Hermes loop is expensive even when the head looks cheap.

## Required Proof Shape

A completed agent turn should leave:

```json
{
  "route_id": "wasm-agent.avatar-chat.ui",
  "workspace_root": "/local/plugins/wasm-agent",
  "status": "completed",
  "changed_files": ["public/styles.css"],
  "checks": ["static css check"],
  "token_usage_total": 12345,
  "components": {
    "head": 1000,
    "bridge": 11345
  }
}
```

A failed turn should leave:

```json
{
  "status": "blocked",
  "error": "route_contract_missing",
  "missing": ["workspace_root"],
  "tokens_spent_before_block": 0
}
```

## Migration Plan

1. Remove product-selector route heuristics from `server/static_server.py`.
2. Add a machine-readable route contract registry for wasm-agent surfaces.
3. Resolve `route_id` and `workspace_root` before direct-head dispatch.
4. Include route contract fields in the direct-head envelope and bridge task.
5. Make Hermes reject missing route contracts instead of broad-searching.
6. Add budget stop rules for repeated search/poll/tool loops.
7. Add tests that prove avatar-chat CSS requests route to
   `plugins/wasm-agent` without selector-specific code.
8. Add a harness promise for "route contract resolves for avatar-chat UI".

Until migration is complete, any new hardcoded product term added to routing
code is a regression.

## Design Standard

The target agent should feel like a superior local-native collaborator:

- fast because it knows the map
- cheap because it does not ask a model to rediscover known structure
- strong because every action is scoped and provable
- autonomous because missing primitives become contracts, not user chores
- LLM-native because every state/action/proof surface is compact and explicit
