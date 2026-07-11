# Master:frontier V3 — C3 Model-Led Execution

Master:frontier V3 is a Codex-style execution harness made cheap by semantic
operations, host-internal cyphers, and load-on-demand context. It is not an autonomous planner,
multi-agent orchestrator, or deterministic workflow engine.

## Objective

Keep one capable head in control of reasoning. The host supplies the smallest
stable bootstrap, executes one requested tool at a time inside declared safety
boundaries, returns a compact observation, and records proof. Token savings
come from avoiding repeated contracts and unloaded detail, not from starving
the model or replacing its judgment with product heuristics.

```text
C3 bootstrap
  -> head reasons
  -> head requests one semantic operation
  -> host scopes and executes
  -> compact C3 observation
  -> same head continues
  -> plain answer or next tool
  -> host records diff, checks, usage, and proof
```

Provider output is buffered per inference. Only an accepted final answer enters
the assistant message body. Each inference also emits a bounded, redacted
Codex-style trace inside that turn: public model decision, selected semantic
operation and arguments, returned observation, status, and exact usage. Hidden
chain-of-thought is never exposed; the trace is structured execution/dataflow
evidence from the same durable run-event stream.

## Ownership

| Surface | Owner |
| --- | --- |
| Canonical cypher mapping | `public/modules/master-frontier/cyphers-v3.json` |
| Browser V3 identity and output hint | `public/modules/master-frontier/cyphers-v3.js` |
| Bootstrap/action/observation/budget codec | `server/master_frontier/cyphers_v3.py` |
| Model-led execution loop | `server/master_frontier/controller_v3.py` |
| HTTP, provider transport, run DB, side effects | `server/static_server.py` compatibility wiring only |

## Semantic operations and internal cyphers

The model never receives or chooses one-character tool codes. It sees a small,
stable operation contract such as:

```text
@search query='meta-analysis'
@read path='public/modules/meta-analysis/meta-analysis-widget.js' bytes=12000
```

Semantic names cost slightly more per action but avoid extra inference calls
spent learning an artificial mapping. The host resolves each operation to a
declared canonical tool, injects route scope, and enforces its read/write
contract.

Cyphers remain useful behind that boundary. The registry maps canonical tools,
statuses, routes, and proof classes to compact codes for persisted history,
event payloads, cache keys, and receipts. Every run records the registry digest
so those artifacts are replayable. Compact cypher JSON is decode-only
compatibility; it is never advertised in the model prompt.

## Load on demand

The initial bootstrap contains only:

- objective;
- route/surface and workspace root;
- semantic operation signatures;
- a compact state/continuity line when present;
- the output rule and proof boundary.

Verbose transport state, action descriptions, output JSON schemas, full
transcripts, logs, source, runtime state, and prior tool payloads stay unloaded.
The head pulls them through semantic operations. The host stores older history
as cyphers but projects semantic operation/status lines back to the model.
Because provider calls are stateless, previously pulled evidence also remains
available inside one bounded evidence window; otherwise multiple reads could
never be synthesized. Source observations and the accumulated window are capped
so one read cannot consume the whole context.

## Authority boundary

The head owns:

- search terms;
- which source or state to read;
- edit strategy;
- test selection from available bounded tools;
- when enough evidence exists to answer;
- answer reasoning and synthesis.

The host owns:

- authentication and route resolution;
- allowed roots and tool capability enforcement;
- tool execution;
- pre-call token/call admission;
- repeated identical-call blocking;
- semantic observation status;
- exact token ledger, diffs, checks, and final proof.
- buffering provider output and projecting public function/dataflow trace rows.

`tools_first`, executor selection, regex entity plans, automatic source probes,
automatic Hermes dispatch, receipt-count progress, and autonomous repair are
not part of V3.

## Observation truth

C3 separates transport success from useful evidence:

| Code | Meaning | Counts as satisfying evidence |
| --- | --- | --- |
| `o` | non-empty relevant observation | yes |
| `e` | successful tool call with empty result | no |
| `m` | missing capability or unsupported inspection | no |
| `x` | execution error | no |

The head receives all four states and decides the next move. The host never
turns an empty receipt into proof.

Source-dependent questions also classify the investigation outcome separately
from transport status: `found`, `not_found_trusted`, `ambiguous`,
`capability_unavailable`, `scope_missing`, or `execution_error`. A bounded
source gate may finalize from the first three outcomes. Stale/unavailable
capabilities cannot prove absence and require one independent declared fallback
when available; a trusted scoped zero-result is a valid honest final outcome.

## Budget law

The route's provider-token and API-call values are advisory targets by default,
not kill switches. Crossing them remains visible in admission diagnostics, but
the model may continue to a source-backed synthesis. They become hard pre-call
caps only when the envelope explicitly sets `enforcement: hard`. A separate
high emergency call ceiling, the no-progress guard, declared tools, and
read/write roots remain hard boundaries.
The head-output value is a per-call ceiling and does not reserve or consume
tokens merely by being high; the browser default is 8,192 so explicitly long
answers are possible.

Cheapness is measured by:

- initial bootstrap estimated tokens;
- cumulative provider tokens per completed objective;
- number of pulled observations;
- repeated-call count;
- answer/proof correctness.

Low token use with an incomplete or weak answer is a failure. Cheapness should
come from compact contracts and bounded observations, not premature stopping.

## Compatibility

V1/V2 envelopes and controllers remain compatibility lanes for stored tests and
older clients. The PWA sends the V3 schema by default. V3 must not import V2
planning, entity-resolution, autonomous continuation, or answer-shaping policy.

## Verification

```bash
python3 plugins/wasm-agent/tests/master_frontier_cyphers_v3.test.py
python3 plugins/wasm-agent/tests/master_frontier_controller_v3.test.py
node plugins/wasm-agent/tests/master_frontier_cyphers_v3.test.js
python3 plugins/wasm-agent/tests/master_frontier_v3_integration.test.py
node plugins/wasm-agent/tests/wasm_agent_smoke.test.js
python3 tools/context/check-monolith-growth.py
```

These are source and local behavioral proofs. A restarted live server and a
real avatar-chat turn are still required before claiming live V3 behavior.
