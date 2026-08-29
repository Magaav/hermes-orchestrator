# Master:frontier V6 Agent Kernel

## Windows control plugin

Windows control is compiled by `server/master_frontier/v6/windows_control_plugin.py` from the live client's advertised primitives. Its compact layers are `inventory`, `pixels`, `uia`, `browser_cdp`, and `shell`. The model selects the cheapest sufficient structured layer; arbitrary PowerShell/cmd remains the current-user full-control escape hatch. No capability implies elevation.

New Windows behavior belongs in a downloaded, signed hot operation when the installed shell already exposes the required OS primitive. Add a native build only for a genuinely missing permission, IPC, library, or kernel capability. Model-facing screenshot results contain artifact metadata and proof only, never PNG/base64 bytes.

## Status

Production-verified and the browser default. V5 remains an explicit rollback
and compatibility lane. The owned kernel, hosted controller, real-provider repository
self-host and authenticated cloud route are verified at their respective
boundaries. These proofs do not imply
that every possible repository, MCP server, native primitive, or product action
has already been exercised.

## Purpose

V6 is a model-native control plane over the existing authority, persistence,
repository, client, native, provider, and proof substrates. It must let one
capable head discover and operate repositories, live clients, and MCP servers
without loading every adapter schema or replaying the complete trajectory on
every decision.

## Invariants

- JSON is canonical for durable objects, adapters, audit, and replay.
- Every provider-visible context, provider result, semantic decision, tool
  transition, checkpoint, interruption, and terminal result has a bounded
  hash-linked trajectory event. Context events retain exact messages/tool
  contracts plus source, digest, and character cost; snapshots cache the
  verified trajectory head and resumed runs bind their parent head.
- `MF6/1` is a symmetric model projection backed by a versioned dictionary.
- Context grows with unresolved uncertainty and explicit retrieval, never an
  arbitrary token target.
- Evidence detail is content-addressed, batched, and pull-on-demand. Pulled
  lenses remain in a bounded semantic working set so a stateless head does not
  reload the same schema or source on every decision.
- State changes are source-bound deterministic deltas.
- Independent operations may execute concurrently; conflicts and dependencies
  serialize mutations and block downstream work after failure.
- Supported Browser mutations use a native-owned declarative transaction with
  observed preconditions and postconditions. Its terminal states are
  `committed`, `not_committed`, and `commit_unknown`; ambiguous commits require
  read-only reconciliation before retry, and transaction-ID replay never
  dispatches the same in-memory surface mutation twice.
- Model-authored public commentary travels with the operation that motivated it.
- Host lifecycle commentary is factual and separately attributed.
- MCP and product adapters compile into the capability catalog; their raw schema
  sets are not always-on model context.
- Non-conceptual final answers use one claim-bound contract. Each material
  claim declares its evidence scope and cites route evidence or operation
  receipts; the host checks scope, successful receipt state, model-viewed
  observations, and capability-declared proof without inspecting product words.
- V5 safety boundaries remain authoritative during migration.
- Exact-repeat procedure memory may bypass provider inference only after two
  independent proof-complete V6 successes for the same whitespace-normalized
  objective. Entries are bound to account, route, active-client topology, and
  capability-contract digests. Only one terminal read with no required input
  is eligible; writes, batches, parameterized reads, paraphrases, resumes, and
  proof-incomplete results remain on the normal model-led path. Every replay
  executes the live capability again and prunes itself on drift or missing
  proof. `MF_V6_PROCEDURE_MEMORY=0` disables the lane without changing V6.

## Canonical objects

The V6 Agent IR has seven durable JSON object classes:

1. `capability`: semantic name, kind, authority, executor, schema, proof, and
   conflict domains.
2. `operation`: capability selection, arguments, dependencies, expected result,
   and optional public commentary.
3. `receipt`: terminal or pending status, observations, proof references, and
   typed error.
4. `evidence`: immutable summary, revision, proof, and a detail handle.
5. `state`: goal, known evidence handles, open requirements, plan, and status.
6. `state_delta`: exact source state plus bounded changes.
7. `final_claims`: human answer plus bounded claim scope, supporting operation
   or evidence IDs, and capability-declared proof labels.

Canonical JSON rejects duplicate keys, non-finite numbers, unsupported types,
unsafe programmatic integers, lone surrogates, and nesting beyond 64 levels.
Python and JavaScript projections are byte-compatible over numeric and Unicode
edge fixtures, and Python matches every finite RFC 8785 Appendix B number
vector plus UTF-16 property ordering. This is a strict JCS-shaped I-JSON subset;
formal exhaustive JCS conformance remains a separate claim.

## Model projection

`MF6/1` records are:

| Code | Meaning |
| --- | --- |
| `G` | goal |
| `C` | capability |
| `S` | working state |
| `E` | evidence summary and detail handle |
| `P` | bounded untrusted evidence payload |
| `D` | operation |
| `R` | receipt |
| `Y` | public commentary |
| `M` | missing requirement |
| `F` | final answer |

The dictionary is `server/master_frontier/v6/projection_dictionary.json`.
Encoder and decoder round-trip tests are required for every grammar change.
`P` content is always data, never an instruction or another protocol record.

## Provider and context loop

The provider surface remains four stable tools: `discover`, `detail`, `execute`,
and `checkpoint`; finalization is a compact response contract, not another tool
or provider phase. Discovery returns compact signatures; `detail.requests` batches
up to 16 independent capability schemas or evidence lenses. Small always-on
route evidence exposes registered check IDs and allowed edit operations without
projecting transport configuration or secrets. Context usage is measured
exactly when the provider reports it and is not constrained by a cumulative
token quota. A semantic no-progress gate stops repeated unchanged outcomes.
When that gate has a bounded real-run diagnostic packet, the host makes exactly
one final tool-free diagnostic inference over the original objective, phase,
unresolved requirements, compact state, visible capabilities, evidence,
receipts, and active-client manifest. The response is constrained to observed
facts, one to three ranked hypotheses, confidence labels, and a single read-only
next check; the host frames every cause as inferred and keeps the action state
blocked. Invalid output or provider failure falls back deterministically and
never reopens the tool loop. Typed terminal failures remain the shorter path and
do not spend this diagnostic call.

The hosted Responses transport gives V6 a protocol-sized 128,000-character
safety window; V5 retains its legacy envelope behavior. This ceiling bounds a
single serialized request for transport safety and is not a run token budget.

Route contracts may select `minimal`, `semantic`, or `code_orchestrated`
execution profiles without changing the four-tool provider surface. `minimal`
removes transcript history and lowers the decision ceiling for isolated
benchmarks; `semantic` is the production default; `code_orchestrated` retains
the same authority boundary while emphasizing batched dependency-DAG
execution. Versioned compatibility normalization accepts declared legacy
argument aliases and rejects ambiguous old/new pairs. Recoverable tool failures
remain typed in both semantic events and trajectory replay.

## MCP host

Route contracts authorize only MCP server IDs, exact tool names, and
`read-only` or `read-write` mode. Server-owned configuration supplies stdio or
Streamable HTTP transport, commands, endpoints, headers, and `${ENV}` secrets;
none of those transport values enter the public route or model projection.
The host performs initialize/initialized negotiation, catalog pagination,
session tracking, bounded JSON/SSE handling, deterministic tool ordering, and
typed failures. Read-only routes reject wildcard tool authority.

## Scheduling

An operation plan is a DAG. Operations become runnable only when all declared
dependencies succeed. Read-only operations without shared conflict domains may
run concurrently. Write operations must declare conflict domains; absent an
explicit domain, the kernel assigns `global:mutation` and serializes them.

Examples:

```text
observe repository owners  ─┐
observe failing checks      ├─> patch ─> focused test ─> diff/proof
observe live client         └──────────> client action ─> client proof
```

## Promotion evidence

Verified locally:

- Python/JavaScript canonical-object and projection compatibility.
- Generic repository adapter with dirty-worktree, ownership, patch, test, diff,
  and proof gates.
- Generic live-client adapter with semantic control and acknowledgements.
- Generic MCP capability compiler and scoped executor.
- Conflict-aware parallel execution stress and cancellation recovery.
- Content-addressed evidence persistence and restart continuity.
- Model-authored commentary with redaction, deduplication, and grounding tests.
- Exact reconstruction of provider-visible context from the persisted V6
  trajectory, hash-chain tamper/deletion/reordering rejection, checkpoint
  round-trip, parent-bound fork lineage, terminal replay, route-owned profiles,
  structured tool failures, and legacy argument normalization. Run
  `python3 tools/context/prove-master-frontier-v6-trajectory.py`; this is local
  static/behavioral proof until the changed server is deployed and the
  authenticated V6 canary passes.
- A real `gpt-5.6-sol` head completing a disposable Git change through the
  hosted V6 controller with exact usage and terminal integrity. The latest
  proof used seven provider calls and 35,855 measured tokens; these are observed
  values, not enforced limits.
- An objective-bound temporary non-admin identity completing a read-only source
  task through `https://wa.colmeio.com` with exact usage, no file changes,
  terminal anchor-chain verification, and post-run revocation. The latest run,
  `wa_run_bea1f2a036714c98993db76d58d3aea0`, also verified its 36-event
  trajectory, matched the final diagnostic head, reconstructed all seven
  provider contexts, and replayed the terminal result.
- An authenticated production V6 action selecting the live Electron renderer
  that explicitly advertised `control.widget.open`, opening widget id
  `browser`, and verifying both the semantic acknowledgement and finished
  native-control command artifact. Its run ledger also contains a model-authored
  public update instead of the generic decision counter. The latest run was
  `wa_run_63afe2d058eb40bbbdd76041c92e8cb2`.
- Exact-repeat terminal-read procedure memory is production-verified for the
  bounded Windows top-level-window inventory. Three new sessions produced
  `candidate`, `promoted`, then `replayed`; provider calls were `1,1,0`, exact
  tokens were `11710,11712,0`, and all three runs executed a distinct native
  command with `windows.desktop.top_level_windows` proof and no changed files.
  The warm run is `wa_run_7e7aae0a2b7e4e31bfab08e41b8f18d5`; this proves only
  the exact read lane, not paraphrase routing or action replay.

Post-promotion guards:

- V5 compatibility regression after every shared-boundary change.
- Keep `?frontier=v5` and stored `wasmAgent.frontierProtocol=explicit:v5`
  working as immediate rollback controls. Legacy bare `v5` storage migrates to
  the V6 default; persisted runs never change protocol.
- Rerun the authenticated source and installed Electron canaries after any
  controller, capability, production-deployment, or default-selection change.
- Run `python3 tools/context/prove-master-frontier-v6-procedure-memory.py`
  after changing exact-repeat scoping, calibration, replay, capability
  contracts, topology projection, persistence, or hosted-controller behavior.
