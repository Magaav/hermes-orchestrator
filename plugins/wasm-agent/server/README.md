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

The current browser default is Master:frontier V5. V3 remains the explicit C3
compatibility lane and sends a compact
semantic-operation bootstrap to one capable head. The head answers directly or
requests exactly one semantic operation; the host maps it to a declared tool,
scopes and executes that tool, returns a compact semantic observation, and calls the same head again. Internal cyphers compress receipts and persisted history but are not model-facing. The host
does not choose `tools_first`, infer entity search strings, or autonomously
dispatch Hermes. See `../MASTER_FRONTIER_V3.md`.

Canonical V3 ownership:

- `../public/modules/master-frontier/cyphers-v3.json`: shared mapping;
- `master_frontier/cyphers_v3.py`: bootstrap/action/observation/budget codec;
- `master_frontier/controller_v3.py`: model-led execution loop.

V1/V2 handling below remains a compatibility lane for older clients and tests.

The first V4 slice is an explicit `protocol=v4-source-investigation` opt-in and
also requires `investigation_mode=source-investigation-read-only`. Run creation
persists that selection immutably; absent/legacy values decode as V3. V4 owns a
two-frontier-call read-only path under `master_frontier/{investigation,evidence,
completion,gate_v4,controller_v4,run_protocol}.py`, reusing this server's
provider, run-event, redaction, trace, token, interruption, and replay substrate.
It cannot edit repositories or claim runtime/deployed/build/installed/production
proof. See `../MASTER_FRONTIER_V4_SOURCE_INVESTIGATION.md`.
V4 reuses configured provider transport but owns its phase messages and a
12 KB model-visible evidence projection. The gate cannot accept handles omitted
from that projection. One typed re-probe may merge evidence for ambiguity,
contradiction, incomplete coverage, or capability recovery without exceeding
the three-call ceiling.

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

Envelope V2 timeline events are the controller-facing proof lane for direct-head
turns. The server persists and streams compact events for:
`llm.inference.started`, `llm.reason.summary`, `semantic.decision`,
`command.proposed`, `command.accepted`/`command.rejected`,
`command.dispatched`, `command.started`, `evidence.received`/
`evidence.missing`/`command.failed`, `llm.inference.completed`,
`turn.usage.updated`, `gate.started`, `gate.decision`, `answer.started`, and
`answer.final`. A second LLM inference is invalid unless new evidence or a
typed missing/failure event exists after the previous decision; violations stop
with `loop_contract_violation`.

V3 provider deltas are buffered until the current inference resolves. Raw
semantic-operation text does not stream into the human answer. The existing
per-turn action chain receives compact `LLM decision`, function-call, and
returned-evidence rows from structured run events; arguments/results are
redacted and bounded, while exact usage is persisted after every inference so
failed or interrupted turns remain accountable.

V5 treats a request for an already-completed action as a stalled-planning
signal, then runs an explicit evidence-sufficiency assessment. Successful
owner/focused-range source coverage or a scoped runtime snapshot/proof permits
completion-only synthesis; one arbitrary successful read/inspection does not.
Search-only evidence instead exposes bounded suggested reads, and missing
primary evidence terminates honestly as `evidence_incomplete` after one repair.
A provider that requests a tool during completion-only synthesis is stopped
with `no_semantic_progress`. A `network-timeout` receives one bounded retry;
the retry becomes completion-only only when the same evidence assessment is
sufficient. A second timeout remains a resumable typed interruption.

V5 coding work is fail-closed at four owned boundaries. `authority.py`
intersects route capabilities with structured task authority and request class;
`repository_reads.py` and `repository_actions.py` provide bounded redacted
reads plus preimage-bound transactional edits; `repository_checks.py` runs only
route-registered argv with bounded in-memory head/tail rings, an absolute
deadline, process-group cleanup, and a typed leak result when an escaped
descendant keeps a pipe open past the grace period;
and `repository_diff.py` produces one bounded porcelain receipt including
untracked files. `v5/operation_ledger.py` binds every mutation, check, diff, and
proof to a causal revision and one route-wide Git state fingerprint, so any
dirty or untracked route-file change invalidates older verification. Reads can
stream arbitrary late line ranges; search uses its own route-owned scan ceiling
rather than the smaller source-index ingestion cap. Transaction journals live
beside durable server state and block new writes when recovery is corrupt.

Restart continuity is server-owned. The controller persists content-free,
digest/scope-bound checkpoints after meaningful loop transitions and reloads
them only under the same user, session, route, and source run. Recent completed
turns use compact SQLite JSON extraction rather than loading full final
trajectories. Model input uses `MF5/2`, tool names instead of duplicate schemas,
one shared 32 KB evidence budget, and a bounded twelve-decision/twelve-tool
trajectory. `head_tokens_max` bounds each provider output. Provider-token and
API-call values remain observable targets unless the request explicitly selects
hard enforcement; hard runs require a positive route-owned per-call input
reservation, subtract the larger host-derived serialized-request bound, enforce
cumulative remaining allowance, and require measurable usage. Browser
avatar-chat uses advisory mode because its provider input cannot be counted
exactly before dispatch. Exact returned usage and separate attempt/success counts
are persisted in either mode. Operation-ledger paths
are prefix-coded and capacity-checked before mutation, while startup recovery
pages unfinished runs in bounded batches. These changes have local static/behavioral proof; authenticated
deployed provider behavior remains unverified.

Task modality comes from declared intent/evidence, never from the presence of
`runtime.inspect`. Runtime mode requires a route-declared entity and projects
its exact compact id/kind in `MF5/2`. A same-session follow-up becomes an
implementation only when its immediate same-route parent has source/runtime
proof, the current turn is an explicit referential mutation request, and the
route owns edit authority. Blocked or capability-incomplete workflows stop
before provider dispatch; completion-only decisions cannot execute raw hidden
tools. Retry projection ends
after successful recovery without replenishing its durable retry budget.

`master_frontier/runtime_snapshot.py` defines the read-only runtime snapshot
boundary used by registered `kernel.inspect(runtime_entity)` actions. It
accepts only bounded redacted identity, availability, freshness, capabilities,
counters, unknowns, and proof references, then exposes a compact model
projection. It does not collect runtime state, poll, control a host, or grant
Docker/device/production access. A trusted collector and proof lookup remain a
separate live-evidence integration gate.

`master_frontier/runtime_snapshot_collector.py` is the first trusted adapter for
that boundary. It opens only the wasm-agent run store in SQLite read-only/query-
only mode, scopes rows by exact user and route, scans at most 64 recent rows,
and emits aggregate counters plus one opaque proof reference. Run ids, user ids,
sessions, objectives, replies, event bodies, database paths, and control access
do not cross the snapshot boundary. Run history is reported as `degraded`
evidence because the collector deliberately does not claim current live state.
The bounded action is registered through `kernel.inspect`; it remains a
historical run-store projection, not live host introspection.

`master_frontier/runtime_proof.py` resolves `runtime.proof.get:<id>` references
without a proof-index database. It rescans the same bounded read-only user/route
scope, recomputes each compact proof digest, and returns only status timestamps,
freshness, redaction metadata, and a receipt digest for an exact match. Wrong
user, route, entity, malformed id, missing source, and stale evidence remain
explicit. Exact proof lookup is model-callable only through the authenticated,
route-scoped runtime action dispatcher.

`master_frontier/runtime_actions.py` defines the model-facing
`runtime.snapshot.get` and `runtime.proof.get` schemas. Model arguments contain
only route id, entity id, and the opaque proof id; authenticated user identity,
database path, freshness ceiling, capabilities, and allowed entities remain
host authority. Its dispatcher rejects unsupported fields, capability denial,
and route/entity mismatch before invoking either trusted adapter. These actions
are registered under `kernel.inspect`; they do not grant shell, control, device,
Docker, or current-live-state access.

Repository/UI object questions use a `source` evidence floor. Their completion
gate accepts a conclusive `found`, `not_found_trusted`, or `ambiguous` receipt;
route resolution alone is insufficient. Stale indexes, missing scope, and
execution failures remain inconclusive and must not be phrased as evidence that
an object does not exist.

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

V3 resolves route/workspace and publishes semantic operations before the provider
call, but the head chooses the tool sequence. Legacy `task_contract`,
`tools_first`, and executor fields may still be present in transport state for
V1/V2 compatibility; they do not control the V3 loop.

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
