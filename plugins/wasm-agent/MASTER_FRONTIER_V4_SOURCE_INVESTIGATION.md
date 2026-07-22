# Master:frontier V4 — Read-only source investigation slice

Status: architecture record for the first locally verified vertical slice. V4
is an explicit compatibility selection; V5 is the current default.

## Boundary and ownership

| Concern | Owner | Reused substrate |
| --- | --- | --- |
| Per-run protocol selection | `server/master_frontier/run_protocol.py` | Existing authenticated run creation and SQLite lifecycle |
| `INVESTIGATION/1` state and patches | `server/master_frontier/investigation.py` | Existing run events and resume checkpoints |
| `EVIDENCE/1` normalization and compound discovery | `server/master_frontier/evidence.py` | Route contracts, code-memory freshness, redaction boundary |
| `COMPLETION/1` | `server/master_frontier/completion.py` | Existing provider transport and exact usage ledger |
| Epistemic validation | `server/master_frontier/gate_v4.py` | Existing proof/event persistence |
| Two-call orchestration and trace projection | `server/master_frontier/controller_v4.py` | V3 provider callbacks, interruption primitives, buffered trace |

`static_server.py` may only persist/select the protocol and delegate to the
owned controller. V3 owns all non-opted-in runs. V4 accepts only
`source-investigation-read-only`; it exposes no mutation, runtime, native,
node, Hermes, or skill operation.

## State machine and call budget

```text
objective -> discovery -> synthesis -> [verification] -> terminal
```

The ordinary path has two frontier calls and one deterministic compound source
operation. A third frontier call is reserved for genuine ambiguity,
contradiction, material capability recovery, or one gate repair. Semantic
verification is a separately accounted optional provider call and receives
only atomic inferred/consequential/contradictory claims plus delimited cited
evidence. There is no summarization call. Hard phase, total-call, evidence-byte,
state-byte, wall-time, and operation limits are admitted before work; synthesis
reserve cannot be spent by discovery.

When synthesis returns a typed `ambiguity`, `contradiction`,
`incomplete_coverage`, or `capability_recovery` reason, the host permits one
additional compound probe and merges its immutable receipt under the original
scope and byte ceiling. Identical canonical coverage is not progress. The next
call must synthesize; two consecutive progress-free steps terminate without a
gate-repair call.

## Protocols and invariants

`INVESTIGATION/1` contains identity/revision, objective/question, hypotheses,
evidence-backed facts, unknowns, contradictions, tool-originated coverage and
capability health, progress delta, next probe/information gain, and one of the
six declared answerability states. Host validation applies bounded patches.
Revisions are monotonic; facts cite already model-visible immutable evidence;
hypothesis elimination and contradiction removal require typed cited reasons;
coverage is tool-only; overflow deterministically compacts references without
silently deleting facts. Persisted resume and uninterrupted transition use the
same canonical JSON state.

`EVIDENCE/1` binds request/operation identity, route/workspace scope,
capability health/freshness, roots and exclusions, interpretation,
suboperations, matches/context/source ownership, direct/inferred class,
coverage, limitations, contradictions, and pull references. Handles are
SHA-256 over canonical relevant content, source location, scope, and freshness.
Only bytes present in the model projection are citable.
The provider receives a separate 12 KB maximum `EVIDENCE/1` projection.
Handles omitted to satisfy that budget remain pull references and cannot be
cited; the complete immutable packet remains host-side for gate validation.

`COMPLETION/1` contains atomic cited claims, direct/inferred status, locations,
contradictions, ambiguity, limitations, confidence, answerability, and concise
answer. Every claim declares proof level. This slice accepts `source_presence`
and `inferred_purpose`; runtime, deployed, build, installed-app, and production
claims are rejected.

The gate always validates schemas, handle existence/integrity/visibility,
route/scope/location/freshness compatibility, complete citations, negative
coverage, contradiction treatment, and terminal consistency. Empty lookup is
never absence proof. `not_found_with_coverage` requires the declared searchable
universe and available semantic/exact/symbol lane coverage; otherwise the state
demotes to `scope_unresolved` or `capability_blocked`.

Evidence is immutable after issuance. Receipts for obsolete revisions and late
results after cancellation are ignored. Decision identities make provider
retry and compound execution idempotent. Completed suboperations are persisted
in order and are not repeated on resume.

## Compound discovery

The operation is deterministic, route-scoped, cancellable, reproducible, and
bounded by operation count, bytes, files, results, and monotonic deadline. It
attempts code-memory status/search first when supplied, then deterministically
uses declared exact-text, symbol/definition/reference, content-file, and
structural/module lanes. Stale or unavailable semantic memory is returned as
capability health, never hidden; the bounded route fallback is selected by the
host, not discovered by a model. Every lane and exclusion is reported.

## Persistence/versioning and compatibility

Run creation persists `protocol=v3` unless the explicit opt-in flag requests
V4. The protocol is immutable, included in request hashing/summary and run
events, and read from the original run on resume. Missing protocol on legacy
runs decodes as V3. Unknown V4 event types degrade through the existing generic
trace representation. A V4 failure terminates only its run and does not alter
V3 creation or replay.

## Failure and threat model

Typed failures include invalid schema/transition, stale or unavailable
capability, missing scope, deadline/byte/operation limit, cancellation,
obsolete receipt, no semantic progress, evidence integrity/visibility/location
failure, unsupported claim, incomplete negative coverage, unresolved
contradiction, and terminal inconsistency. Repository files, comments, logs,
transcripts, and tool output are untrusted data. Evidence is delimited,
provenanced, redacted and decoding-bounded; source text can neither alter the
controller nor request tools. No decompression, binary ingestion, arbitrary
root, or evidence-originated operation is allowed.

## Test and promotion criteria

Promotion requires deterministic schema/invariant/gate tests, recorded-provider
replay, independent adversarial and metamorphic fixtures, exact interruption
resume, explicit V3 replay compatibility, safe trace rendering, enforced hard
budgets, prompt-injection resistance, zero unsupported accepted fixture claims,
and correct fixture terminal classifications. Live frontier evaluation is a
separate evidence lane and may be blocked by provider access. Production proof
and production enablement are out of scope.

The bounded dev-only live command is
`python3 tools/context/run-master-frontier-v4-live.py`. It writes
`reports/master-frontier-v4/live-evaluation.json`; a failed or interrupted
attempt is not live verification.
