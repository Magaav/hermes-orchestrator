# LLM-Native Agent Source Harvest

This harvest records only the parts of the referenced systems that should shape
the next wasm-agent production slice.

## Applicable Patterns

| Source | Keep | Why it matters for wasm-agent |
| --- | --- | --- |
| Asolaria recall notes | Deterministic address, dereference, content receipt, cache honesty | Known structure should be resolved by route id and file hash, not rediscovered by broad model search. Proof should include compact receipts such as path, bytes, and sha256. Cache hits reduce repeat work but are not "free compute." |
| codebase-memory-mcp | Structural map backend, bounded graph queries, no built-in LLM | The kernel needs map/lookup tools that answer route, file, symbol, and impact questions cheaply. The model should translate intent, while deterministic tools return bounded facts. |
| Simplicio | Repo map, memory recall, deterministic edits, sealed receipts, visible token savings | The product target is cheap execution: local map first, deterministic operations when possible, provider calls only for judgment, and every run showing exact cost where available. |
| DeepSpec / DSpark | Draft/speculative decoding as provider acceleration | Useful later for model-serving economics. It is not part of this route-contract slice because the current need is deterministic routing, lookup, proof, and token accounting. |

## Acceptance Gates Added To This Slice

1. Route ids are deterministic registry entries, not runtime product-string
   branches.
2. `route.resolve` resolves from the registry only and never scans source.
3. `map.summary`, `lookup.files`, and `lookup.symbol` stay bounded by the
   resolved route contract.
4. File lookup returns proof receipts: route id, path, byte count, and sha256
   when the file exists.
5. Hermes/provider dispatch under the direct-head kernel fails closed with
   `route_contract_missing` unless a registered route contract is resolved.
6. Exact provider usage is persisted per quest, turn, and provider call.
7. Raw provider usage is stored separately from normalized exact fields.
8. Estimated context-window pressure is labeled separately from provider token
   usage and never mixed into exact totals.

## Rejected For This Slice

- Importing or depending on codebase-memory-mcp as a hot-path service. A tiny
  route lookup API is enough for this slice.
- Training or integrating DSpark/draft models. That belongs to a future
  provider-runtime optimization track.
- Adding CSS selectors, DOM classes, UI labels, or filenames to
  `static_server.py` as routing knowledge.
