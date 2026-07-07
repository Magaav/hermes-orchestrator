# wasm-agent Server

`server/` owns both local Python processes used by `wasm-agent`.

- `static_server.py`: account-gated PWA/backend server on `0.0.0.0:8877`
  through `scripts/start_wasm_agent.sh` by default, with
  `HERMES_WASM_AGENT_HOST` available to override the bind address.
- `bridge.py`: wasm-agent-owned Hermes bridge on `127.0.0.1:8790`.
- `routes.py`, `schemas.py`, and `auth.py`: bridge route, schema, and token
  helpers for fleet/node state, resources, logs, lifecycle actions, task
  submission, and host resource summaries.

The bridge routes requests through the Hermes Orchestrator CLI/API boundary.
It must not import Hermes Agent internals or patch runtime node state directly.

## LLM-Native Direct Envelope

`POST /agent/provider/envelope` and
`POST /agent/provider/envelope/stream` are the compact LLM-native head lanes
for admin avatar-chat and related embedded-agent decisions. They intentionally
bypass the Hermes turn/session context and send only a bounded envelope to the
configured receiver. Non-admin users must stay on the existing bridge/provider
chat path.

The envelope must include `objective`. Preferred fields are `trace_id`,
`compact_state`, `capabilities`, `constraints`, `evidence_refs`,
`allowed_actions`, `action_schemas`, `budget`, and `output_schema`. Secrets in
the provider-proxy path are redacted before prompt assembly. With
`receiver=openai-responses`, the stream route starts a durable direct-head
worker, sends the raw envelope directly to the OpenAI Responses API using
`OPENAI_API_KEY` or `WASM_AGENT_OPENAI_API_KEY` from the process environment or
`wa.env`, and stores only compact redacted run events including replayable
`head.delta` chunks. With `receiver=openai-codex`, the same durable worker uses
server-side ChatGPT/Codex OAuth credentials from `WASM_AGENT_CODEX_ACCESS_TOKEN`,
`OPENAI_CODEX_ACCESS_TOKEN`, `WASM_AGENT_CODEX_AUTH_JSON`, `~/.hermes/auth.json`,
or `~/.codex/auth.json`, then streams to
`https://chatgpt.com/backend-api/codex/responses` with Codex-compatible headers.
The browser never receives the OAuth token, and token refresh remains the
responsibility of the Hermes/Codex login flow. If the direct head returns a
validated `dispatch.hermes` action, wasm-agent dispatches it through the
existing bridge/Runs API surface only when the action is explicitly declared as
a bounded harness/subagent dispatch (`role=subagent_harness` or `harness=true`)
with a resolved route, allowed capabilities, proof request, and escalation
reason. Hermes must not be used as the server-default fallback when the
direct-head provider is unavailable, and it must not be auto-called to repair
an implementation answer that lacks changed-file proof; those cases fail with
typed contract errors. Run replay streams compact trace actions for envelope,
head decision, explicit Hermes dispatch, touched files, changed files, tests,
and proof events. These routes bypass context, not admin gating, auth, provider
routing, diagnostics, or account gating.

Direct-head routes that can dispatch tool or source work must preserve the same
post-turn audit contract as `/agent/session/message`: capture before/after
worktree state, return `changed_files`, include timeline checkpoint diagnostics,
and emit changed-file/proof run events. The UI already renders diff and
Stepback from that payload; do not replace it with a text-only proof summary.

## Agent Tool Layer

`POST /agent/tools/*` is the wasm-agent-owned local tool protocol for
route-scoped work. It is MCP-shaped but intentionally implemented as a small
JSON HTTP surface first, because the existing server already owns auth, route
contracts, run events, and token ledgers.

The MCP contract layer is not owned by `static_server.py`. New model-facing
tool vocabulary, action schemas, repair policy, prompt projections, route/code
lookup policy, and token-budget behavior belong in `server/master_frontier/`
with focused tests. `static_server.py` is allowed to provide HTTP/auth wiring,
route-contract loading, run-event recording, provider calls, and side-effect
execution, but it must delegate MCP policy to Master:frontier modules.

Master:frontier emits a compact `task_contract` before provider or harness
selection. The contract classifies intent, pins `route_id` and
`workspace_root`, lists allowed capabilities, names `tools_first`, selects the
initial executor (`local_kernel`, `provider_head`, or `blocked`), declares
proof requirements, and carries block codes. Capability questions such as
"can we ship a widget?" must plan as `capability_inquiry` with
`code.memory.search`/`kernel.inspect` before any Hermes path. Implementation
requests must plan for local route-scoped action and changed-file proof.

Current kernel tools: `kernel.capabilities`, `kernel.resolve`,
`kernel.inspect`, `kernel.act`, and `kernel.prove`. These are the generic
LLM-facing Agent Kernel contract. The model should call them when an answer
depends on unknown route, runtime, workspace, file, timeline, cost, or proof
state. Runtime/entity inspection must stay generic and bounded: it reports the
resolved route identity, declared runtime capability, lookup/proof handles,
scoped or recent run evidence, and explicit unknowns. Text mentions from a
model turn are evidence context, not entity-resolution proof. The observed
product/entity is only a fixture for the generic contract.

Current route/provider tools under the kernel: `route.resolve`, `map.summary`,
`lookup.files`, `lookup.symbol`, `file.read_bounded`, `patch.apply_scoped`,
`test.run_focused`, `git.diff_summary`, `proof.collect`, `cost.status`,
`hermes.capabilities`, and `hermes.dispatch_bounded`.

Current code-memory tools: `code.memory.index`, `code.memory.status`,
`code.memory.search`, and `code.memory.impact`. These are Master:frontier-owned
wrappers around `codebase-memory-mcp` for token-saving code intelligence. They
must be used as route-scoped lookup primitives before broad file reads or
Hermes dispatch when the question is about repository structure, symbols,
callers/callees, or change blast radius. The external binary is optional at
runtime; if it is missing, the tools return a typed
`code_memory_unavailable` result rather than forcing a broad search fallback.
Set `WASM_AGENT_CODE_MEMORY_BIN` or `CODEBASE_MEMORY_MCP_BIN` when the binary is
not on `PATH`. If no env override is present, Master:frontier first looks for
the repo-local vendor binary at
`/local/tools/vendor/codebase-memory-mcp/v0.8.1/codebase-memory-mcp`, then falls
back to `codebase-memory-mcp` on `PATH`. Route roots are indexed/query-scoped by
the normalized project id used by the binary, for example
`/local/plugins/wasm-agent` becomes `local-plugins-wasm-agent`.

Agents working from the terminal should use
`python3 tools/context/code-memory-query.py --route-id <route> "<query>"` as
the primary codebase route for symbol/ownership/architecture lookup. Fall back
to `rg` only when code-memory is unavailable, stale, or the task requires exact
raw-text matching. This keeps broad file reads out of prompt context until the
graph has narrowed the target.

Route-bound tools resolve `server/agent_route_contracts.json`, enforce
allowed read/write roots, keep reads byte-bounded and redacted, and only run
focused checks registered on the route contract. Hermes dispatch is a
last-resort bounded harness/subagent tool: it requires a resolved route,
capability need, budget or route budget, proof contract, explicit escalation
reason, and `role=subagent_harness` or `harness=true` before using the
bridge/Runs API.

The direct-head envelope adds only a compact generic kernel projection:
local-first mode, the resolved route id, the five kernel primitive names, the
Master:frontier `PLAN`/`task_contract`, and the rule that unknown state
requires kernel resolution/inspection/proof before answering. Do not add
product names, node names, selectors, or one-off prompt affordances to handle
an observed miss; add or fix the generic kernel contract or route registry and
prove it with the observed case as a fixture.
