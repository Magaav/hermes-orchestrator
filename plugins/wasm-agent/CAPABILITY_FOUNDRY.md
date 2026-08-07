# WASM Agent Capability Foundry

Status: `implemented-unverified`

The Capability Foundry is the governed path by which wasm-agent discovers,
tests, promotes, demotes, and routes executable functions. It is not a planner,
model trainer, or mechanism for upgrading claims from prose.

## Objective

Turn an unfamiliar artifact into a bounded capability only when its executable
contract and evidence survive the appropriate gate:

```text
discover -> candidate -> calibrate/verify -> promote -> monitor -> demote
```

The source-owned registry is
`server/master_frontier/capability_registry.json`. Runtime projections are
produced by `server/master_frontier/capability_foundry.py`.

## Capability Classes

| Class | Required evidence | Permitted promoted use |
| --- | --- | --- |
| `exact` | deterministic fixtures, negative controls, artifact digest, declared limits | Direct call inside the tested contract |
| `predictive` | sealed balanced train/holdout benchmark, baseline, confidence interval, topic stability | Calibrated domain only |
| `anti_predictive` | predictive gate plus independently proven transform | Declared transform only |
| `proof` | distinct failure detection, clean control, bounded verifier, trusted anchor where required | Evidence verification only |
| `hypothesis` | executable output and provenance | Suggestion only; no authority |

## States

- `discovered`: an artifact or function was identified.
- `candidate`: an executable contract and owner exist.
- `calibrated`: behavioral evidence exists but routing is not authorized.
- `promoted`: every class-specific gate and route authority requirement passed.
- `demoted`: newer evidence invalidated an earlier promotion.
- `rejected`: the capability failed its contract or duplicates a simpler
  primitive without measurable benefit.

State is separate from the canonical claim status. A capability can be a
`candidate` while its software claim is `implemented-unverified`.

## Promotion Invariants

Every promoted record must have:

- a stable capability id, class, owner, version, and executable entry;
- a pinned artifact or source digest;
- explicit input, output, limits, side effects, and failure codes;
- a named focused verifier and fresh passing evidence;
- a route/capability allowlist;
- a compact model projection;
- invalidation paths;
- a fallback or stop behavior;
- no unresolved blocker.

Predictive capabilities additionally require a preregistered transform and
sealed holdout. A below-chance binary function may be inverted only when the
direct 95% interval is below chance, the inverted interval is above chance,
train and holdout agree, and every declared topic remains above chance.

## Demotion

Demotion is automatic at evaluation time when:

- a registered invalidation path changed after the evidence timestamp;
- the artifact digest no longer matches;
- required proof is missing, stale, or failing;
- runtime capability or route authority disappeared;
- a predictive holdout or topic-stability gate no longer passes;
- a simpler baseline matches the result without the claimed extra value.

Demoted and candidate capabilities are not projected into the Master:frontier
hot path. Hypothesis capabilities may be queried explicitly but carry
`authority=none`.

## ASOLARIA Boundary

ASOLARIA is the first fixture. Its receipt, inspection, and calibration
functions are executable candidates. Its GGUF is catalog data, not an
inference runtime. ASI and accuracy claims remain unverified. The first actual
WASM question adapter is explicitly rejected for routing: on a sealed,
balanced 180-case arithmetic holdout its direct extractor scored 55%, inversion
scored 45%, and the majority baseline scored 50%. Event integrity
and the append-only anchor store are promoted proof capabilities after an
authenticated production canary verified terminal persistence, a separate
final chain, answer completion, and synthetic-account revocation. Their stated
limit remains unchanged: same-host administration is outside the trust model.

## Verification

```sh
python3 tests/master_frontier_capability_foundry.test.py
python3 tests/master_frontier_event_integrity.test.py
python3 tests/master_frontier_event_anchor_store.test.py
python3 tools/context/prove-master-frontier-authenticated-canary.py --origin https://wa.colmeio.com
node --experimental-vm-modules public/modules/asolaria/runtime.test.mjs
node --experimental-vm-modules public/modules/asolaria/calibration.test.mjs
node --experimental-vm-modules public/modules/asolaria/qa-adapter.test.mjs
```
