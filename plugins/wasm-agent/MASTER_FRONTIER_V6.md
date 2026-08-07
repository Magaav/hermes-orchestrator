# Master:frontier V6 Agent Kernel

## Status

Production-verified and the browser default. V5 remains an explicit rollback
and compatibility lane. The owned kernel, hosted controller, real-provider repository
self-host, authenticated cloud route, and installed Electron Browser-widget
control are verified at their respective boundaries. These proofs do not imply
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
- `MF6/1` is a symmetric model projection backed by a versioned dictionary.
- Context grows with unresolved uncertainty and explicit retrieval, never an
  arbitrary token target.
- Evidence detail is content-addressed, batched, and pull-on-demand. Pulled
  lenses remain in a bounded semantic working set so a stateless head does not
  reload the same schema or source on every decision.
- State changes are source-bound deterministic deltas.
- Independent operations may execute concurrently; conflicts and dependencies
  serialize mutations and block downstream work after failure.
- Model-authored public commentary travels with the operation that motivated it.
- Host lifecycle commentary is factual and separately attributed.
- MCP and product adapters compile into the capability catalog; their raw schema
  sets are not always-on model context.
- V5 safety boundaries remain authoritative during migration.

## Canonical objects

The V6 Agent IR has six durable JSON object classes:

1. `capability`: semantic name, kind, authority, executor, schema, proof, and
   conflict domains.
2. `operation`: capability selection, arguments, dependencies, expected result,
   and optional public commentary.
3. `receipt`: terminal or pending status, observations, proof references, and
   typed error.
4. `evidence`: immutable summary, revision, proof, and a detail handle.
5. `state`: goal, known evidence handles, open requirements, plan, and status.
6. `state_delta`: exact source state plus bounded changes.

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

The provider surface is four stable tools: `discover`, `detail`, `execute`, and
`checkpoint`. Discovery returns compact signatures; `detail.requests` batches
up to 16 independent capability schemas or evidence lenses. Small always-on
route evidence exposes registered check IDs and allowed edit operations without
projecting transport configuration or secrets. Context usage is measured
exactly when the provider reports it and is not constrained by a cumulative
token quota. A semantic no-progress gate stops repeated unchanged outcomes.

The hosted Responses transport gives V6 a protocol-sized 128,000-character
safety window; V5 retains its legacy envelope behavior. This ceiling bounds a
single serialized request for transport safety and is not a run token budget.

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
- A real `gpt-5.6-sol` head completing a disposable Git change through the
  hosted V6 controller with exact usage and terminal integrity. The latest
  proof used seven provider calls and 35,855 measured tokens; these are observed
  values, not enforced limits.
- An objective-bound temporary non-admin identity completing a read-only source
  task through `https://wa.colmeio.com` with exact usage, no file changes,
  terminal anchor-chain verification, and post-run revocation. The latest run
  was `wa_run_0c68f5659e98403eb307a75676bb1aa9`.
- An authenticated production V6 action selecting the live Electron renderer
  that explicitly advertised `control.widget.open`, opening widget id
  `browser`, and verifying both the semantic acknowledgement and finished
  native-control command artifact. Its run ledger also contains a model-authored
  public update instead of the generic decision counter. The latest run was
  `wa_run_63afe2d058eb40bbbdd76041c92e8cb2`.

Post-promotion guards:

- V5 compatibility regression after every shared-boundary change.
- Keep `?frontier=v5` and stored `wasmAgent.frontierProtocol=explicit:v5`
  working as immediate rollback controls. Legacy bare `v5` storage migrates to
  the V6 default; persisted runs never change protocol.
- Rerun the authenticated source and installed Electron canaries after any
  controller, capability, production-deployment, or default-selection change.
