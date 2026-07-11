# Master:frontier V5

V5 is an explicit opt-in persistent natural-tool loop. Frontier receives a
compact objective/route/trajectory projection and chooses `search`, `read`,
`inspect`, or a final answer. Route enforcement, execution, event persistence,
receipts, cancellation, and usage accounting remain host-owned.

V5 has no objective-level token ceiling. Exact tokens are telemetry. The loop
stops on completion, cancellation, typed capability failure, repeated
equivalent actions, two progress-free decisions, repeated malformed output,
or provider/tool failure. Provider context/output limits and account quotas are
external transport policy, not evidence or completion policy.

`search` also returns a deterministic compact focus map for the highest-ranked
owning file: line count, top-level symbols, merged relevant read ranges, and
related tests present in the bounded evidence. This carries forward V4's useful
evidence orientation without adding a separate discovery-model phase.
The generic provider proxy forwards optional native function descriptors through
the owned `provider_tools.py` adapter. V5 advertises tools while evidence is
incomplete, canonicalizes native absolute paths to route-relative identity, and
withdraws tools from both transport and model context once the owning source is
fully read. Final prose is not forced through JSON response mode because live
evaluation showed that it degraded answer completeness.

## Selection

V5 is the PWA default for Master:frontier. `?frontier=v3` and
`?frontier=v4-source-investigation` (or the equivalent local-storage value)
remain explicit compatibility/rollback paths.

## Owned implementation

- `server/master_frontier/v5/`: loop, context, natural tools, trajectory,
  policy, and typed errors.
- `server/master_frontier/controller_v5.py`: thin adapter to existing route,
  provider, event, token, and run persistence infrastructure.

## Verification

```sh
python3 tests/master_frontier_v5.test.py
node tests/master_frontier_source_investigation.test.js
```

The canonical live fixture is `criticize meta-analysis widget`. It must read
`public/modules/meta-analysis/meta-analysis-widget.js`, produce useful
source-grounded criticism, persist every provider/tool step, and avoid
repeating completed work after resume. Local/source proof is not production
proof.
