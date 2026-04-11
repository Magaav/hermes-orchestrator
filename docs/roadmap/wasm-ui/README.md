# `wasm-ui` Track

Exploration track for a visual control plane and high-performance observability interface for Hermes Orchestrator.

## Objective

Provide a UI layer for fleet operations while keeping CLI-first operation intact.

## Focus Areas

- Fleet and node status overview (`orchestrator` plus `worker` runtimes).
- Operational views for lifecycle, task activity, and log streams.
- Observability workflows for `/local/logs/nodes/<node>/...` and `/local/logs/attention/nodes/<node>/...`.
- Performance experiments for graph rendering and event visualization where WebAssembly can be justified.

## Data and Contract Alignment

- Reuse existing orchestrator runtime contracts and log topology.
- Prefer consuming current command/data surfaces before introducing new control-plane APIs.
- Keep node governance boundaries explicit (shared plugin/script ownership remains orchestrator-managed).

## Non-Goals (Current Phase)

- Replacing `horc` or making CLI workflows optional.
- Reworking core node runtime architecture.
- Declaring a production UI stack before perf and operational validation.

## Milestones

1. Define UI surface map (views, required signals, data ownership).
2. Prototype observability-heavy screens with realistic log/event volumes.
3. Benchmark rendering/event pipeline options (with and without WASM).
4. Publish a recommendation with rollout and fallback strategy.

## Status

`Exploring`.
