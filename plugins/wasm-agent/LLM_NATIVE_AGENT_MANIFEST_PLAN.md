# LLM-Native wasm-agent Manifest Plan

> Historical V1/V2 plan. It is not the current execution contract. Master:frontier
> V5 is the default persistent natural-tool execution lane; see
> `MASTER_FRONTIER_V5.md`. V3 remains the explicit C3 compatibility path.
> Autonomous planner,
> `tools_first`, and executor-selection language below must not be reintroduced
> into the V3 hot path.

This plan turns the wasm-agent direction into an implementation track. It is
written to prevent the exact failure mode where an agent misses the product map,
delegates broad reasoning to Hermes, burns tokens in the wrong roots, and then
patches `static_server.py` with another product string.

## What We Are Trying To Build

We are trying to build a high-quality, strong, autonomous wasm-agent that is superior
inside this product domain because it does not act like a generic chat model
with filesystem access.

Quality comes first. Token savings are valid only when they preserve or improve
answer quality, proof, and convergence. A cheap weak answer is false economy
because the next corrective turn spends the "saved" tokens anyway. Cheap means
known structure is never rediscovered by a large model. Routing,
workspace ownership, likely files, local symbols, allowed capabilities, stop
rules, and proof requirements are deterministic first. Model calls are reserved
for ambiguity, planning, synthesis, and judgment, and the model must be allowed
to reason fully when the objective needs it.

Strong means the agent has explicit product contracts. It knows which surface is
being discussed, where source lives, which roots are writable, which tools are
available, what evidence is required, and when to stop. It does not broad-search
runtime node worktrees because a UI CSS task used words it did not recognize.

Autonomous means the user does not babysit routing, repeat file paths, ask a
second agent to watch, or manually infer whether the run is going in the right
direction. The run produces its own route, plan, current step, proof handles,
and exact token usage.

LLM-native means the agent's world is exposed through compact contracts and
pull-on-demand detail: route ids, small dictionaries, capability schemas, status
codes, counters, budgets, proof artifacts, and bounded lookup handles. Human UI
remains readable, but model input is not a screenshot, raw log dump, or verbose
debug JSON blob.

The target is not "Hermes but cheaper." The target is a wasm-agent kernel with
its own route map, protocol, tool server, proof ledger, and action adapters.
Hermes is forbidden for the current direct-head baseline and must not be a
fallback, product router, architecture owner, or required capability. It can be
revisited later only as an explicitly bounded optional adapter.

## Failure Being Corrected

The bad loop was:

```text
user asks for avatar-chat UI/CSS change
  -> direct head lacks durable route contract
  -> Hermes is asked to infer ownership
  -> Hermes searches unrelated roots
  -> token spend grows without direction proof
  -> server code gets a new product-string heuristic
```

That is architectural debt. A selector list in runtime code is not a map. A
model guessing roots is not autonomy. A final answer with token totals but no
per-turn ledger is not cost transparency.

## Non-Negotiables

1. Product strings, CSS selectors, DOM classes, filenames, and feature labels do
   not belong in runtime routing branches.
2. Route ownership is loaded from a declarative registry and tested.
3. A missing route fails as `route_contract_missing`; it does not trigger broad
   model search.
4. Hermes is a provider behind a contract, not the planner of last resort.
5. Every user quest and every agent turn records exact provider token usage when
   the provider returns it.
6. Exact usage and estimated usage are never mixed under the same field.
7. Context-window pressure and billable token usage are separate UI concepts.
8. Repeated uncertainty is harvested into route contracts or harness promises.
9. The UI timeline is generated from structured run/proof events, not scraped
   prose.
10. A run that cannot prove route, scope, checks, and token usage is incomplete.

## Plan Iteration

### Plan v0

Add a route registry, pass `route_id` and `workspace_root` into direct-head
prompts, and make Hermes stay inside that root.

### Critique v0

This fixes the immediate wrong-root failure but is too shallow. It still treats
the model prompt as the main control plane. It does not define a tool protocol,
skill map, exact token ledger, proof ledger, missing-capability behavior, or
UI timeline source of truth. It also leaves Hermes too close to the hot path.

### Plan v1

Create a wasm-agent kernel around route contracts, local lookup tools, budget
guards, provider adapters, and a proof ledger. Hermes becomes one adapter. The
kernel resolves routes before provider calls and records usage for every call.

### Critique v1

This is directionally right but still implementation-heavy. It needs a compact
wire format, a clear migration from current `static_server.py` behavior, exact
quest-vs-turn accounting, acceptance gates, and a frontier prompt that prevents
the next agent from turning the architecture back into heuristics.

### Plan v2

Build the agent as a small deterministic operating layer plus bounded model and
skill adapters:

```text
user quest
  -> wa-kernel
  -> route registry
  -> compact turn envelope
  -> bounded lookup/tool server
  -> optional provider adapter
  -> proof ledger
  -> token ledger
  -> timeline projection
  -> harness harvest
```

This is the accepted plan below.

## Final Architecture

### 1. wa-map

`wa-map` is the durable product map. It is data, not code branches.

It owns:

- route ids
- surface names
- owner packages
- workspace roots
- allowed read/write roots
- likely paths
- symbol indexes
- test/check commands
- proof requirements
- capability requirements
- provider escalation policy
- token, call, and time budgets

Example route contract:

```json
{
  "route_id": "wasm-agent.avatar-chat.ui",
  "surface": "avatar-chat",
  "owner": "plugins/wasm-agent",
  "workspace_root": "/local/plugins/wasm-agent",
  "allowed_read_roots": ["/local/plugins/wasm-agent"],
  "allowed_write_roots": ["/local/plugins/wasm-agent"],
  "likely_paths": ["public/styles.css", "public/app.js"],
  "lookup_handles": ["route.files", "route.symbols", "route.tests"],
  "caps": ["repo.read", "repo.edit", "test.run", "proof.report"],
  "provider_policy": {
    "default": "local-first",
    "hermes": "bounded-skill-only",
    "missing_route": "fail"
  },
  "budget": {
    "head_tokens_max": 3000,
    "provider_tokens_max": 8000,
    "api_calls_max": 6,
    "wall_ms_max": 90000
  },
  "proof": ["route_id", "changed_files", "checks", "token_ledger"]
}
```

The registry may contain human-readable aliases, but runtime code only asks the
registry to resolve. It does not embed aliases as special branches.

### 2. wa-kernel

`wa-kernel` is the deterministic turn controller.

It owns:

- quest id and turn id creation
- route resolution
- budget opening and stop rules
- capability validation
- lookup handle dispatch
- provider adapter selection
- proof collection
- token ledger aggregation
- structured event emission for the UI timeline

The kernel does not make product edits itself. It scopes and controls the work.

### 3. wa-protocol

`wa-protocol` is the compact model and tool ABI.

Baseline prompt envelope:

```text
WA1
Q q_8fc2
T 2
OBJ <bounded user objective or summary handle>
R wasm-agent.avatar-chat.ui
ROOT /local/plugins/wasm-agent
CAP read,edit,test,proof
BUD h=3000 p=8000 calls=6 wall=90s
DEPTH normal|deep|free
FLOOR conceptual|route|proof|runtime
ROUTE_INTENT conceptual|informational|implementation|runtime_support
A focused|playful|urgent|debugging|reflective
STATE_MODE blocked_on_proof|exploring|converging|debugging|reflective
CAPS_VERIFIED repo.read,proof.report
COVERAGE rich|thin|ambiguous|stale
ANCHORS turn3:decision:auth-proof turn7:preference:brevity
RECALL_BUDGET reflective:transcript_turns=10
RECENT session_local_clipped_turns
REFLECT model_reflection=self_model_not_proof
EVID route,receipts,recall_handles
STATE_WRITEBACK delta,feedback,last_action,last_feedback,next
LOOK files,symbols,tests,diff
PROOF route,files,checks,tokens
STOP no_progress=2 missing_route=fail
```

Expanded data is pulled through handles:

```text
lookup(route.files)
lookup(route.symbols, "agent-message-body")
lookup(route.tests)
lookup(run.timeline, q_8fc2)
```

The envelope is intentionally not a full UI dump. It gives the model enough
structure to ask for the next cheapest fact.

`DEPTH free` is reserved for explicit architectural critique or high-trust
reflection turns. It does not disable proof discipline; it tells the provider
to reason fully while the kernel keeps repeated uncertainty cheap through
harness promises and evidence receipts. The protocol remains model-agnostic and
does not branch on model capability metadata.

`FLOOR` is the objective's evidence floor. It keeps conceptual critique from
over-dispatching, while implementation and runtime/entity questions still
require proof or runtime evidence before current-state claims.

`COVERAGE` and `ANCHORS` let the head reason about compression quality without
fetching full history. Provider output may include `state_feedback` so the
state writer can repair thin or ambiguous envelopes on the next turn.
`RECALL_BUDGET` is a bounded session-local transcript allowance for reflective
turns only; it is not RAG and not broad persistent memory.
If a bounded transcript cache is already present, `RECENT` may project a tiny
clipped excerpt for reflective turns. It is session-local and non-persistent.

`ROUTE_INTENT` separates route provenance from route-relevant reasoning. `A` is
a bounded affect shorthand, not a personality blob. `SELF_CHECK` is emitted as
deterministic run diagnostics, not a second model pass.
`REFLECT` may permit `model_reflection` as labeled self-model/metaphor for
reflective prompts. It never counts as inspected proof.

`STATE_MODE` is the problem phase and stays separate from affect. `CAPS_VERIFIED`
lists only capabilities proven or bound for this route/session. Do not include
token-cost pressure fields in the head envelope; exact ledgers remain
observability for humans and harness analysis, while the model prioritizes
quality and proof.

`STATE_WRITEBACK` is emitted after finalization as a compact run-ledger receipt
from `state_delta` and `state_feedback`. It gives the next CSC/STATE writer a
bounded target without creating broad hidden memory.

### 4. wa-tool-server

The backend should expose a small tool server, MCP server, or equivalent
Master:frontier tool layer. Its job is to give the model and providers bounded,
LLM-native actions instead of raw filesystem wandering.

Minimum tools:

- `route.resolve(objective, surface_hint)` -> route contract or
  `route_contract_missing`
- `map.summary(route_id)` -> tiny route summary
- `lookup.symbol(route_id, query)` -> bounded symbol matches under route root
- `lookup.files(route_id)` -> likely files and file hashes
- `file.read_bounded(route_id, path, range)` -> scoped read
- `patch.apply_scoped(route_id, patch)` -> scoped edit with write-root check
- `test.run_focused(route_id, check_id)` -> bounded verification
- `proof.collect(quest_id, turn_id)` -> proof ledger projection
- `cost.status(quest_id, turn_id)` -> exact and estimated token usage
- `skill.query(route_id, need, caps, budget)` -> provider offers

If the current Master:frontier endpoint cannot provide these as bounded tools,
build a new wasm-agent tool server instead of overloading Hermes.

### 5. Skill Providers

Skill providers are adapters behind the kernel:

- local deterministic tools
- Hermes bounded skills
- native bridge operations
- Codex/frontier model calls
- future small local models

Provider request:

```json
{
  "quest_id": "q_8fc2",
  "turn_id": 2,
  "route_id": "wasm-agent.avatar-chat.ui",
  "workspace_root": "/local/plugins/wasm-agent",
  "caps": ["repo.read", "repo.edit", "proof.report"],
  "budget": {
    "tokens_max": 8000,
    "api_calls_max": 6,
    "wall_ms_max": 90000
  },
  "task": "Change only avatar-chat message padding rules.",
  "forbidden": ["broad_search_outside_root", "route_inference"]
}
```

Provider failure:

```json
{
  "status": "blocked",
  "error": "capability_missing",
  "missing": ["repo.edit"],
  "tokens": {
    "exact": true,
    "input": 412,
    "output": 63,
    "cached_input": 0,
    "total": 475
  }
}
```

Hermes may return proposals, diffs, bridge results, and proof. It may not decide
where avatar-chat lives.

### 6. Token Ledger

The token ledger is per quest, per turn, per provider call.

Required fields:

```json
{
  "quest_id": "q_8fc2",
  "turn_id": 2,
  "provider_call_id": "pc_04",
  "provider": "hermes",
  "model": "frontier-small",
  "usage_source": "api_response",
  "exact": true,
  "input_tokens": 1856,
  "output_tokens": 266,
  "cached_input_tokens": 0,
  "reasoning_tokens": 0,
  "total_tokens": 2122,
  "billable_cost_units": null,
  "started_at": "2026-06-30T00:00:00Z",
  "ended_at": "2026-06-30T00:00:07Z"
}
```

Quest total:

```json
{
  "quest_id": "q_8fc2",
  "turn_count": 3,
  "exact": true,
  "total_tokens": 12914,
  "components": {
    "head": 2303,
    "providers": 10611,
    "local_tools": 0
  }
}
```

Rules:

- If a provider returns usage, record it exactly.
- If a provider does not return usage, mark `exact: false` and put the value
  under `estimated_*`, never under exact fields.
- Local deterministic tools report `0` model tokens and normal wall/time costs.
- The UI must show context-window pressure separately from provider usage.
- A "quest required X tokens" number is the sum of exact turn/provider totals
  for that quest, not the current prompt window size.

### 7. Proof Ledger

Every turn writes a compact proof event stream:

```json
{
  "quest_id": "q_8fc2",
  "turn_id": 2,
  "status": "completed",
  "route_id": "wasm-agent.avatar-chat.ui",
  "workspace_root": "/local/plugins/wasm-agent",
  "plan": ["resolve", "edit", "check"],
  "current_step": "check",
  "changed_files": ["public/styles.css"],
  "checks": ["css static scan"],
  "tokens": {"exact": true, "total": 2122}
}
```

The avatar-chat timeline should render this ledger. Long fields must truncate
or wrap inside the timeline, with pull-on-demand detail. The UI should not rely
on a final prose answer to tell the user whether the run is on track.

### 8. Harness Harvest

Repeated uncertainty becomes deterministic:

- second repeat: add route contract or promise candidate
- third repeat: promote to `docs/context/HARNESS_PROMISES.json` or record the
  missing primitive

Immediate candidates:

- `wasm-agent-route-avatar-chat-ui`
- `wasm-agent-no-static-server-routing-heuristics`
- `wasm-agent-token-ledger-exact`
- `wasm-agent-timeline-overflow-safe`

## Migration Plan

### Phase 0: Stop The Bleeding

Remove the current hardcoded selector/product routing heuristics from
`plugins/wasm-agent/server/static_server.py`. Add a failing guard if a future
change puts product strings back into routing code. The first acceptable
replacement is `route_contract_missing`, not broad Hermes fallback.

Exit gate:

- no avatar-chat CSS selector or feature-label route branches in
  `static_server.py`
- avatar-chat route failure is explicit and cheap

### Phase 1: Route Registry

Add a machine-readable route registry for wasm-agent surfaces. Start with
avatar-chat UI, agent timeline, native controls, speech transcription, and
Frontier controls.

Exit gate:

- `route.resolve("avatar-chat padding")` returns
  `wasm-agent.avatar-chat.ui`
- `route.resolve` never searches source
- missing route returns structured `route_contract_missing`

### Phase 2: Kernel And Envelope

Move direct-head dispatch through `wa-kernel`. The head receives a compact
`WA1` envelope with route, root, caps, budgets, lookup handles, and proof
requirements.

Exit gate:

- direct-head requests include route contract fields
- provider tasks include the same route contract
- no provider receives an unscoped broad-search task

### Phase 3: Tool Server

Expose bounded route/map/lookup/patch/test/proof/cost/skill tools. Prefer a
dedicated wasm-agent tool server if Master:frontier cannot be made strict and
cheap without more indirection.

Exit gate:

- the model can inspect files through route-scoped lookup
- patches are rejected outside allowed write roots
- focused checks are discoverable by route id

### Phase 4: Hermes Demotion

Convert Hermes from general agent fallback into a skill provider. It receives
only scoped tasks and must return exact usage, proof, or structured failure.

Exit gate:

- Hermes refuses missing route contracts
- Hermes refuses broad search outside allowed roots
- repeated no-progress calls stop automatically

### Phase 5: Exact Token Ledger

Store exact usage for every provider call and aggregate it by turn and quest.
Expose both compact and detailed projections to the UI.

Exit gate:

- every run has quest total, turn totals, provider-call totals
- exact versus estimated usage is explicit
- context-window usage is labeled separately from billable provider tokens

### Phase 6: Timeline Projection

Render the proof ledger in avatar-chat as a compact run timeline: objective,
route, plan, current step, files touched, checks, token usage, status, and proof
handles.

Exit gate:

- timeline content cannot overflow its container
- active runs show direction before final answer
- final runs show proof and residual risk without requiring prose scraping

### Phase 7: Evaluation Suite

Create representative cheapness tests:

- avatar-chat CSS edit
- agent timeline overflow fix
- speech module route
- native bridge route
- unknown surface
- repeated no-match loop

Exit gate:

- simple known-route tasks stay under the declared budget
- unknown-route tasks fail fast
- no broad Hermes fallback appears in logs
- proof ledger and token ledger are present for every case

## Acceptance Gates

The architecture is not done until these pass:

1. A known avatar-chat UI request resolves to
   `plugins/wasm-agent` before any model call.
2. A missing route returns `route_contract_missing` before Hermes is invoked.
3. Hermes cannot search outside the route contract root.
4. Runtime routing code contains no product selector lists.
5. Token usage is exact per provider call when provider usage exists.
6. Quest total equals the sum of turn/provider exact totals.
7. The UI labels context-window pressure separately from token usage.
8. The timeline shows current step, route, files, checks, and tokens during a
   run.
9. Long timeline fields wrap, truncate, or expand on demand instead of
   overflowing.
10. The second repeated uncertainty creates a promise candidate; the third is
    promoted or blocked with a missing primitive.

## Frontier Implementation Prompt

Use this prompt for the best available frontier implementation pass:

```text
You are implementing the LLM-native wasm-agent architecture in /local.

Objective:
Build the first production-shaped slice of the cheap, strong, autonomous
wasm-agent. Replace reactive routing and broad Hermes fallback with a
route-contract kernel, bounded lookup/proof tools, exact token ledger, and a
compact timeline projection. Hermes must become a scoped skill/bridge provider,
not the product router or planner of last resort.

Read first:
- /local/AGENTS.md
- /local/docs/context/README.md
- /local/docs/context/HARNESS.md
- /local/docs/context/MAP.md
- /local/plugins/wasm-agent/AGENTS.md
- /local/plugins/wasm-agent/README.md
- /local/plugins/wasm-agent/LLM_NATIVE_AGENT_ARCHITECTURE.md
- /local/plugins/wasm-agent/LLM_NATIVE_AGENT_MANIFEST_PLAN.md
- /local/plugins/wasm-agent/server/README.md if touching backend
- /local/plugins/wasm-agent/DESIGN.md if touching UI/CSS

Non-negotiables:
- Do not add product strings, CSS selectors, DOM classes, filenames, or feature
  labels to runtime routing code.
- Remove existing selector/product route heuristics from static_server.py before
  adding new routing behavior.
- Route ownership must be declarative and testable.
- A missing route returns route_contract_missing; it must not invoke Hermes.
- Hermes may only execute bounded skill/provider tasks under a resolved route
  contract.
- Every provider call must report exact usage when the provider returns usage.
  Estimated usage must be labeled estimated and never mixed into exact fields.
- The UI must separate context-window pressure from token usage.
- Keep changes scoped. Do not refactor unrelated speech/native/runtime code.

Implementation order:
1. Add a route registry for wasm-agent surfaces, starting with
   wasm-agent.avatar-chat.ui.
2. Add a resolver that returns route_id, workspace_root, allowed roots, caps,
   budgets, lookup handles, and proof requirements.
3. Remove the hardcoded selector/product routing heuristic from
   plugins/wasm-agent/server/static_server.py.
4. Route direct-head and provider dispatch through the resolver.
5. Make missing route/capability return structured failure before provider
   dispatch.
6. Add a token ledger with quest, turn, and provider-call records.
7. Aggregate exact token usage by quest and expose it to avatar-chat.
8. Add a compact proof/timeline event projection with overflow-safe rendering.
9. Add focused tests for route resolution, missing route, Hermes refusal without
   route, token aggregation, and timeline overflow safety.
10. Add or update a harness promise if this is the second or third repetition of
    a manually checked uncertainty.

Verification:
- python3 tools/context/check-harness-promises.py
- python3 tools/context/check-context-sync.py
- focused wasm-agent backend tests for route/provider/token behavior
- focused JS/UI test or browser proof for timeline overflow behavior
- rg proof that static_server.py no longer contains product selector routing

Report:
- changed files
- route contracts added
- exact tests/checks run
- token-ledger behavior proven
- any estimated usage fields that remain and why
- residual risks
- next loop-shortening promise or contract candidate
```

## First Implementation Slice

The first slice should be deliberately small:

1. Remove the bad static server route heuristic.
2. Add route registry and resolver.
3. Scope avatar-chat UI requests through that resolver.
4. Add exact token ledger aggregation for existing provider responses.
5. Render compact timeline fields without overflow.
6. Add tests proving those five facts.

Do not start by redesigning every provider. A small, enforced, measured slice is
the fastest path to the autonomous agent.
