# LLM-Native wasm-agent Architecture

This is the target architecture for avatar-chat, embedded agent routing, Hermes
dispatch, context budgeting, and per-turn proof.

The current executable contract is `MASTER_FRONTIER_V3.md`. The older manifest
plan is retained for V1/V2 history only.

## Goal

Build a high-quality, strong, Codex-style execution head with cheap proof loops.

Quality and correctness outrank token minimization. Token savings are only real
when they preserve or improve answer quality, proof, and convergence. A
low-token weak answer is not a saving if it forces another corrective turn.
Cheap means the default path uses deterministic routing, compact state, local
indexes, bounded lookup tools, and strict scoping before any large model loop;
it must not pressure the model to under-reason when depth is needed.

Strong means the agent understands product ownership and proof contracts before
acting. It should know that avatar-chat UI belongs to `plugins/wasm-agent`,
native shell work belongs to `native/`, generated runtime state is not source,
and Hermes node work is a separate runtime boundary.

Model-led means one capable head owns reasoning, search terms, tool choice,
edits, tests, and synthesis. The host supplies route/safety boundaries, executes
requested tools, and verifies evidence. It must not replace model judgment with
an autonomous planner or regex workflow.

LLM-native means the agent gets explicit compact contracts, not a human UI dump
or vague prose. It should operate from stable fields, route ids, capability
reports, action schemas, budgets, counters, and proof handles.

## Non-Goal

Do not build wasm-agent by adding more product strings to `static_server.py` or
similar runtime files. A list of CSS selectors, DOM classes, feature labels, or
one-off regexes is not a map. It is reactive monkey-patching.

Do not use Hermes as the planner of last resort for product routing. For the
current Master:frontier direct-head path, Hermes is forbidden as a fallback or
required capability. wasm-agent must be capable without Hermes. Hermes may be
revisited later only as an explicitly bounded optional adapter; it must not
discover the product map by broad search.

Do not build an autonomous planner/executor around the head. `tools_first`,
executor selection, entity-query heuristics, automatic probes, and receipt-count
progress are V1/V2 compatibility behavior, not the V3 target.

## Architecture

The correct flow is:

```text
user turn
  -> route contract resolver
  -> C3 cypher bootstrap
  -> head chooses one load-on-demand tool or answers
  -> host scopes and executes the requested tool
  -> compact semantic observation
  -> same head continues
  -> host proof
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

Depth is a contract hint, not a provider identity branch. Normal turns stay
bounded by default, reflective or root-cause turns may declare
`DEPTH deep`, and the top tier may declare `DEPTH free` as an open reasoning
hint when the user explicitly wants architectural critique. The harness and
proof loop still keep the run cheap by making repeated uncertainty
deterministic.

Reflective turns may also carry a tiny `RECALL_BUDGET` hint. This is not a
persistent memory layer or RAG path; it only says that reflective/deep critique
may spend a small bounded `transcript.read` window when exact recent
back-and-forth improves answer quality. Quality and proof correctness outrank
token minimization.

When the request already includes a bounded transcript cache, reflective turns
may project a tiny `RECENT` excerpt from that session-local cache. `RECENT` is
redacted, clipped, non-persistent, and never a substitute for persistent memory
or broad transcript replay.

Evidence floor declares the minimum proof lane for the objective:
`conceptual` for reflection/critique, `route` for route-backed answers,
`proof` for implementation or durable claims, and `runtime` for live entity
state. Conceptual turns must not trigger defensive runtime inspection just
because route/entity proof is available.

The envelope should include compact evidence and recall receipts such as route
contract presence, local proof counts, CSC continuity, and pull-on-demand
handles like `transcript.read` or `memory.search`. Do not add model capability
metadata to the contract; the architecture assumes a capable model and keeps
the protocol model-agnostic.

State coverage and anchors are the self-improving layer. `COVERAGE
rich|thin|ambiguous|stale` tells the head whether the compressed state is
enough for the current turn. `ANCHORS` carries two to four compact prior-turn
handles such as `turn3:decision:auth-proof`; the model can pattern-match before
paying for `transcript.read`. Answers may include optional `state_feedback`
with coverage, ambiguity classes, and suggested anchors so the next CSC/STATE
writer can improve the envelope without a full memory dump.

Route intent and affect keep the envelope humane without making it verbose.
`ROUTE_INTENT conceptual|informational|implementation|runtime_support` tells
the head whether route proof is reasoning material or just provenance. `A
focused|playful|urgent|debugging|reflective` is a tiny affect shorthand for
tone continuity. A deterministic `SELF_CHECK` diagnostic should report whether
the final answer claimed verification or action without matching proof/action
evidence.

Capability and problem-state hints should stay tiny. `CAPS_VERIFIED` lists only
capabilities proven/bound in the current route or session; it is a decisiveness
signal, not a broad health dump. `STATE_MODE
blocked_on_proof|exploring|converging|debugging|reflective` captures the
problem phase separately from affect. Do not add cost-pressure fields to the
head envelope; exact token ledgers remain observability for humans and harness
analysis, not a reason for the model to reduce quality.

Reflective self-report is allowed only when labeled. A `REFLECT` projection may
tell the head that `model_reflection` is permitted as self-model/metaphor, not
inspected factual proof. The head must still keep proof-honesty for claims like
verified, confirmed, inspected, and changed.

State writeback is the bounded feedback path. Provider output may include
`state_delta` and `state_feedback`; the run ledger must persist a compact
`STATE_WRITEBACK` receipt with the delta, feedback, last action, last feedback
status, and suggested next-envelope hints. This is not broad persistent memory;
it is replayable evidence for the next CSC/STATE writer.

## Hermes Role

Hermes is not part of the current direct-head baseline. It is forbidden as a
default fallback and should be treated as a future optional adapter only after
the wasm-agent kernel can route, act, and prove without it.

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
2. Expose the cheapest mapped lookup first; the head chooses when to call it.
3. Prefer local indexes and bounded reads in the declared workspace root.
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
- model-led because one capable head retains reasoning authority across tools
- LLM-native because every state/action/proof surface is compact and explicit
