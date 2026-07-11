# wasm-agent Context Contract

## Purpose

`plugins/wasm-agent` owns the active WASM Agent PWA, cloud/local backend,
native bridge API, Frontier controls, native release feed, client-first account
state, and product UI surfaces.

## Ownership

- Product UI, browser/workspace, account, relay, native download/update, and
  Frontier backend work belongs here by default.
- Native OS shells live in `/local/native`; keep platform packaging and OS
  integration there, and keep shared web/runtime contracts here.
- Local runtime state under `state/` is gitignored deployment state, not source.

## Local Contracts

- Production native clients must use `https://wa.colmeio.com`; never route
  production behavior to `127.0.0.1:8877`, `localhost`, `0.0.0.0`, or emulator
  dev origins.
- Keep the app client-first where possible. Server work should be explicit:
  auth, presence/relay, sync, backup, provisioning, native diagnostics, or
  release metadata.
- Keep feature work omni-device by default. Implement shared product behavior in
  the PWA/runtime lane with browser APIs, WASM, WebGPU/WebNN where available,
  downloaded model/runtime artifacts, browser cache/IndexedDB, and version/SHA
  metadata before adding native shell code.
- Keep embedded-agent and model-facing protocols LLM-native by default. Send the
  smallest stable text envelope that lets the model decide what to query next,
  then expose bounded lookup tools for detail. Do not make verbose JSON
  snapshots, raw logs, screenshots, protobuf/base64 blobs, or human-debug views
  the default prompt contract.
- Do not encode wasm-agent routing by adding CSS selectors, DOM class names,
  UI labels, filenames, or other product strings to `server/static_server.py`
  or similar runtime code. Route ownership belongs in the context route map,
  this contract, or a dedicated machine-readable route registry with tests.
  Runtime code may enforce a resolved route contract; it must not become a pile
  of reactive routing heuristics.
- The MCP/tool contract layer belongs under `server/master_frontier/`, not in
  the `server/static_server.py` monolith. New tool vocabularies, model-facing
  action schemas, repair policies, prompt projections, code-memory query
  policy, and token-saving lookup contracts must be added to Master:frontier
  modules with focused tests. `static_server.py` may provide auth, HTTP
  routing, route-contract loading, run-event recording, and side-effect
  execution only; it must delegate MCP policy to the owning module.
- Before adding any line to `server/static_server.py`, check for an existing
  owned Master:frontier module that can hold the durable logic. If one exists,
  patch that module and keep `static_server.py` as delegation only. If no
  module exists, create the smallest focused `server/master_frontier/` module
  first. A net line-count shrink in `static_server.py` is insufficient by
  itself when the added behavior could live in an owned module.
- For codebase understanding, ownership lookup, symbol search, caller/callee
  tracing, and change blast-radius work, use the Master:frontier code-memory
  lane before broad `rg` or multi-file reads. From the terminal, prefer
  `python3 tools/context/code-memory-query.py --route-id <route> "<query>"`
  for the first pass. Use `rg` after code-memory when the graph is missing,
  stale, unavailable, or when exact raw-text matching is explicitly needed.
- Master:frontier V3 is a Codex-style model-led execution harness. The host
  resolves route, workspace, capabilities, safety limits, cypher version, and
  budget before provider work; the head owns search terms, tool choice, edit
  strategy, tests, and synthesis. `tools_first`, executor selection, regex
  entity plans, and receipt-driven autonomous continuation are not V3 control
  surfaces.
- Model-facing context must use compact semantic operations plus load-on-demand
  detail. The canonical versioned C3 mapping is host-internal for receipts,
  persisted history, and replay. The host maps exactly the semantic operation
  requested by the head to a declared tool, injects route scope, returns a
  compact semantic observation, and records proof. Empty or unsupported
  receipts must not count as evidence.
- Hermes is not a fallback planner or autonomous subagent in the V3 hot path.
  Named node capability/chat tools may expose it as an explicitly selected,
  route-bounded capability; provider unavailability and missing proof remain
  typed errors.
- When avatar-chat, direct-head, or run-api observation exposes a weak answer,
  do not add a node name, product string, selector, filename, or one-off prompt
  affordance to fix that observed miss. First name the missing generic kernel
  contract: capability discovery, objective/entity resolution, bounded runtime
  inspection, scoped action, proof collection, or harness promise. The observed
  case may then become a fixture proving the generic contract.
- Use native shells only for non-negotiable OS/browser constraints: background
  wake-word listeners, OS services, native permissions, package/signing
  behavior, accessibility/media projection, foreground services, or hardware/OS
  primitives unavailable to the browser. Keep native as the smallest primitive;
  keep UI, model selection, diagnostics, and policy in the shared runtime.
- Frontier/control routes must stay authenticated, audited, bounded, and
  operation-based. Do not add arbitrary shell execution or unauthenticated
  global reload controls.
- Before applying app code, use the repo-wide Pre-Code Performance Reflection:
  prefer the shortest correct path with fewer phases, listeners, renders,
  reflows, recalculations, bridge calls, polling loops, and rebuild/runtime
  cycles. If a safe simplification is visible inside the touched boundary,
  apply it as part of the change.
- For Frontier, native bridge, release feed, hot-op, diagnostics, and runtime
  control changes, use the repo-wide Verified Loop-Aware Engineering doctrine:
  separate Builder intent, Watcher evidence, and Gatekeeper decision; prefer
  static, runtime, and behavioral evidence when possible.
- Generated reports, diagnostics, uploaded datasets, pid files, and mutable
  caches stay under `state/` or `reports/` unless a reviewed fixture is needed.

## Work Guidance

- Read `/local/docs/context/MAP.md`, this file, then `README.md` for current
  status, release handoff, and local verification.
- For frontend/UI work, also read `DESIGN.md`.
- For server/API work, also read `server/README.md`.
- For config defaults, also read `conf/README.md`.
- For generated/local state handling, also read `state/README.md`.
- For embedded-agent, avatar-chat routing, context/token economics, run
  timelines, or Hermes dispatch work, read `LLM_NATIVE_AGENT_ARCHITECTURE.md`
  `LLM_NATIVE_AGENT_MANIFEST_PLAN.md`, and
  `LLM_NATIVE_AGENT_SOURCE_HARVEST.md` before source edits.
- Before rebuild-heavy or runtime-control work, prefer live introspection,
  HMR, hot-op, runtime config, downloaded runtime/model metadata, or a small
  diagnostic probe when that safely shortens the loop.
- Keep durable next actions short and actionable. If the handoff grows into a
  log, move details to the nearest focused doc and leave a pointer.

## Verification

- Web/PWA proof: `horc simulate web`.
- Android APK proof: `horc simulate android` with an authorized device/emulator,
  or `horc simulate android --local-report <path>` for copied evidence.
- Broad native feed/build proof: `horc build all` when touching release feed
  generation or cross-platform artifact publication.
- Server tests live under `tests/`; prefer focused smoke/unit checks before
  broad runs.

## Child Context Index

- `README.md`: current behavior, Frontier loop, durable next action, and active
  evidence.
- `server/README.md`: Python backend ownership and runtime notes.
- `conf/README.md`: configuration defaults and deployment knobs.
- `state/README.md`: gitignored runtime state layout.
- `public/native/`: generated native release feed and artifacts; do not edit by
  hand unless explicitly repairing release metadata.
