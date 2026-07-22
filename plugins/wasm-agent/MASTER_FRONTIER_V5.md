# Master:frontier V5

Implementation planning is a distinct read-only task class. Its terminal
artifact is a compact model-authored operational decision (candidate, target
paths, acceptance criterion, blocker, next action, and confidence). Execution
receives the selected decision from the completed-run ledger as one compact
`d` continuity record under a separate mutation-capable contract. The
safe lab orders capability checks from exact patching through navigation,
planning handoff, prioritization, and multi-turn continuity so the first failed
category is observable.

V5 is the default persistent natural-tool loop. Frontier receives a compact
objective/route/continuity projection and chooses one authorized `search`,
`read`, `inspect`, `edit`, `test`, `diff`, or `prove` operation, or a final
answer. Route enforcement, task authority, execution, restart state, receipts,
cancellation, and usage accounting remain host-owned.

The loop stops on completion, cancellation, task-lease expiry, typed capability
failure, repeated malformed output, or unrecoverable provider/tool failure.
Explicit hard policy may also enforce route-owned call, token, or duplicate
limits. An advisory run has no hidden provider-decision, tool-call, duplicate,
or mutation deadline. Authenticated clients may request cooperative cancellation
with `POST /agent/runs/{run_id}/cancel`; cancellation is checked before the next
provider or tool operation and preserves a resumable checkpoint.
or no-progress ceiling; the model chooses how much work the objective needs,
while counters survive restart and remain observable. Timing is
split into independent contracts: `heartbeat_ms_max` for progress visibility,
`provider_call_ms_max` (with legacy `wall_ms_max` as a stricter alias) for one
inference call, registered per-operation timeouts for tests/builds, and
`task_lease_ms_max` for the durable objective. Implementation defaults to a
bounded twelve-hour lease when a route does not declare one. Lease expiry blocks
new investigation or mutation, checkpoints as `task_lease_exhausted`, and still
permits exactly completion-only synthesis after conclusive proof has landed.
Route provider-token and API-call values are observable targets
by default. They become cumulative stops only under explicit
`enforcement=hard`; a hard route must declare a per-call
positive route-owned `input_tokens_max` reservation; the host subtracts the
larger of that value and a conservative bound over the actual serialized
messages/tool schemas. Hard mode fails closed when either the reservation or
measurable returned usage is unavailable. The browser uses advisory mode,
because no provider-independent tokenizer can truthfully guarantee its input
cost before dispatch.
`head_tokens_max` is a per-call output ceiling, never a cumulative run budget.
Exact returned usage is retained in both modes. Account quotas remain external
transport policy.

`search` returns a deterministic compact focus map for the highest-ranked
owning file: line count, top-level symbols, merged relevant read ranges, and
related tests. This orients source work without adding another model phase.
Native provider function descriptors remain available while evidence is
incomplete and are withdrawn once completion-only synthesis begins.

## Compact context and continuity

The model-facing projection is the line-oriented `MF5/2` protocol. Native tool
schemas remain in the provider tool field and are represented in the prompt by
authorized names only, avoiding a second copy. The deterministic empty-state
fixture is measured by the composed proof; its current ratio and input
fingerprint are recorded in the generated artifact.
Primary evidence is stored once in the trajectory, projected under one shared
32,000-character budget, and omitted from final content-free tool receipts.
The `W` record is a compact advisory progress projection: durable decision,
tool, and duplicate counters; merged source-read coverage and overlap; and the
current understand/edit/test/diff/prove stages. It gives the model global
novelty and unmet-work visibility without adding a controller phase or taking
control away from the model.
The generic novelty admission contract rejects a read before execution when
its requested range is already fully covered. A successful search whose source
locations add nothing beyond durable prior search receipts is recorded as
typed non-progress. Neither rule limits decisions or elapsed work: the head
remains free to choose new evidence, mutate, verify, name a blocker, or finish.
When durable receipts cover every line of the route-selected owner, discovery
is complete and `search`/`read` are withdrawn; all remaining authorized
decision, mutation, verification, and completion choices stay model-owned.
Absolute and relative paths are canonicalized against the resolved workspace
before coverage comparison. Deterministic diff retries at the same repository
revision are rejected, while tests and proof may refresh when prerequisite
receipts change. Once an implementation ledger has mutation/check/diff/proof or
a verification ledger has check/proof, V5 withdraws tools and enters final
synthesis; completion no longer depends on the head voluntarily stopping.

Recent completed turns are loaded by one SQLite query that extracts only the
route, objective, answer anchor, status, changed files, and verification level.
A contextual action may inherit implementation class only from the immediately
preceding same-user/session/route source- or runtime-grounded parent, an
explicit referential mutation request, and route-owned edit authority; prior
prose or requests such as “update me” cannot grant mutation. An interrupted run resumes only from a
server-owned checkpoint bound to a digest,
user, session, route-contract digest, and source run. Checkpoints retain counters, compact
receipts, pending action, and the operation ledger, but never raw source,
diffs, or command output. Browser state sends only a checkpoint digest capsule;
it cannot supply trusted trajectory state. A durable action event that landed just
before a crash is reconciled idempotently by action id. Operation postimages use
reversible prefix coding, and an edit is rejected before execution if its paths
cannot fit the reserved restart ledger. Startup reconciliation pages unfinished
runs in fixed-size batches instead of materializing the whole run table.

## Coding authority and proof

Tool availability is the intersection of resolved route capabilities, declared
task authority or request-class defaults, the exact tool capability, and a
nonempty write-root contract. Source investigation stays read-only, runtime
inspection cannot expand into repository work, and missing write roots deny
edits. Capability presence never selects evidence modality: diagnosis defaults
to source investigation unless structured evidence explicitly requests runtime.
Runtime inspection also requires an exact route-declared entity id and kind;
`MF5/2` projects those bounded ids to the head.
Planner block codes and impossible implementation/verification capability sets
stop before provider dispatch and expose no tools.

Repository reads and search share one route-scoped sensitive-path/redaction
policy, bounded streaming traversal, and a single-descriptor read/digest path.
Line reads can reach late ranges without loading the skipped prefix; search and
focus maps stream to a separate route-owned per-file scan ceiling instead of
silently stopping at the smaller source-index ingestion cap.
Private environment files, keys, databases, generated state, binaries, model
artifacts, and archives are not model-readable. V5 edits require the SHA-256 of
the observed preimage (or `expected_absent=true` for creation), validate the
whole operation set before commit, serialize cooperative writers, and stage
postimages plus rollback backups. A compact fsynced journal beside durable
server state is restored on the next server start if the process dies during a
multi-file commit; corrupt recovery state blocks later mutations.

`test` runs only an argv registered by the route contract—never an arbitrary
shell string. Continuously drained pipes retain only bounded head/tail rings,
the child receives a minimal environment, and process-group cleanup runs after
timeouts and normal parent exits. A descendant that escapes the group cannot
hold its inherited pipe open indefinitely: the worker returns a typed leak
failure after a bounded grace period, although PID/cgroup cleanup for such an
escaped process is not yet provided. `diff` uses one bounded Git porcelain
receipt and includes staged, worktree, deleted, renamed, and untracked paths.

Every successful non-dry-run edit advances a causal revision and records exact
postimage hashes. Completion after mutation requires a passing registered check,
a diff covering every mutated path, and scoped proof, all recorded at the current
revision and bound to one worktree digest. Postimages are verified again before
finalization. In Git workspaces the digest also binds HEAD, bounded porcelain
state, and streamed content hashes for every dirty or untracked file inside the
route's write scope; a later or external edit therefore invalidates proof even
when it did not touch a V5 postimage. Calling `kernel.prove` before the other
gates cannot authorize completion.

Source synthesis becomes completion-only only after the whole owner or every
declared focused range has been read. Runtime synthesis requires a scoped
snapshot/proof result. An arbitrary successful read or generic inspection is
not sufficient, cross-modality evidence cannot force completion, and evidence
alone never short-circuits implementation. Completion-only is host-enforced:
raw model JSON cannot execute a hidden tool, and one rejected decision receives
a bounded final-answer repair. Read-only verification cannot finish without a
passing registered check and scoped proof. One transient retry keeps its
durable consumed budget while successful recovery ends temporary evidence
clipping.

## Learning from agent lanes

The lab lane accepts an optional compact event stream, normalizes only public
search/read/edit/command/test/diff/proof/terminal events, hashes arguments,
redacts secrets and runtime identities, excludes private reasoning, and
requires an authoritative terminal event. Loop 5 disqualifies a failed
candidate individually instead of invalidating unrelated passing candidates.
Only digest-bound regression-passing generic patterns may be copied into V5's
small source-owned pattern projection.

A deterministic fake adapter proves the event path. Real Codex, Claude,
Gemini, and other external adapters are not yet wired to it, so cross-agent
trajectory quality and live promotion are not current claims. Semantic and
efficiency ranking can still be reported, but golden-pattern candidates remain
empty unless the report and every lane contain admissible normalized strategy
evidence with observable tool-call counts.

## Selection

V5 is the PWA default for Master:frontier. `?frontier=v3` and
`?frontier=v4-source-investigation` remain explicit compatibility paths.

## Owned implementation

- `server/master_frontier/v5/`: compact context, continuity, causal operation
  ledger, loop, natural tools, trajectory, learned patterns, and policy.
- `server/master_frontier/{authority,repository_reads,repository_actions,
  repository_checks,repository_diff,repository_state,run_recovery,
  session_context}.py`: route/task authority,
  bounded coding primitives, and compact turn reconstruction.
- `server/master_frontier/controller_v5.py`: thin adapter to route, provider,
  event, token, and run persistence infrastructure.

## Verification

```sh
python3 tests/master_frontier_v5.test.py
python3 tests/master_frontier_v5_resilience.test.py
python3 ../../tools/context/prove-master-frontier-v5-evolution.py
node tests/master_frontier_continuation.test.js
```

The authenticated local source profile and exact command are documented in
`../../tools/app-simulator/README.md`.
The evolution above currently has local static and behavioral proof only; it
does not establish a new deployed runtime, production provider, or external
agent-learning claim.
