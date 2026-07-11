# WASM Agent Native Guard

Binding workspace rules for `/local`.

Production WASM Agent Native is cloud-only.

Backend:
https://wa.colmeio.com

Production app URL:
https://wa.colmeio.com/home?native=electron

Localhost 127.0.0.1:8877 is dev-only and forbidden in production.

Current Android device ADB is only reachable through the installed Windows
bridge. Codex/cloud-local `adb devices` is expected to be empty and must not be
treated as Android-disconnected evidence for the wake loop. Use Windows bridge
hot ops/native-control for ADB-backed Android work unless the user explicitly
changes the physical setup.

Never claim the Windows installer is fixed based on source tests or
`win-unpacked`. The final extracted NSIS installer and installed `app.asar`
must pass verification.

Windows login persistence also requires installed-app proof: Google login,
full close/reopen, `https://wa.colmeio.com/home?native=electron`,
`authCookie.hasWaUid: true`, durable cookie expiration metadata, and
authenticated `/auth/session`.

Build success is not runtime proof. Roadmap/future/proposal claims must not be
presented as current software.

## Pre-Code Performance Law

Before applying code, perform a simplification and performance reflection. The
default architecture is the shortest correct path: fewer lifecycle phases,
listeners, renders, reflows, recalculations, bridge calls, polling loops, and
rebuild/runtime cycles when they produce the same correct observable result.

Doing two steps when one step produces the same correct result is architecture
waste. If reflection identifies duplicated state, redundant listeners,
avoidable recalculation, layout thrash, bloated control flow, unnecessary
abstraction, or delayed feedback, simplify the design before editing or include
the simplification in the edit.

Keep the simpler path readable and owned. Extra work is allowed only when it is
explicitly justified by correctness, safety, compatibility, or observability
that shortens future proof/debug loops.

### Pre-Code Monolith Routing Gate

Before applying any code patch, check whether the intended target file is a
known frozen monolith or is 5000+ lines. If yes, do not patch durable logic into
that file first.

Stop and classify the concern with bounded context:

- transport, HTTP, auth, or run persistence
- routing, intent, proof, policy, evidence, answer shaping, or diagnostics
- UI behavior or widget logic
- native shell primitive
- compatibility shim
- deletion or extraction

Then route the concern before editing:

- If an owning module exists, patch the owning module.
- If no owning module exists, create the smallest owning module first.
- The monolith may only keep delegation, bootstrap wiring, compatibility shim,
  or deletion.
- Any exception must use `ARCH_EXCEPTION` with owner, reason, and expiry.

A patch that starts by adding helper functions, policy branches, schemas,
answer-shaping logic, diagnostics contracts, route/entity/proof logic, or other
durable behavior to a monolith is invalid even if tests pass and even if some
other part of the file shrinks. The pre-code reflection must name the owning
module path and the exact monolith line shape that remains.

## LLM-Native Architecture Law

Every durable implementation in this repo should be designed for LLM operation
as a first-class architecture target. Humans still need readable UI and docs,
but the system should also expose compact, explicit, bounded contracts that let
an LLM inspect state, understand capabilities, choose actions, and verify proof
without scraping human-only screens or ingesting large opaque dumps.

Default new state/action/diagnostic surfaces to LLM-native shape:

- tiny always-on summaries plus pull-on-demand detail
- stable names, short field codes, and shared dictionaries for model-facing
  context
- structured APIs/tool results for machines, with compact LLM projections for
  prompts
- explicit capability reports, action schemas, status fields, counters, error
  classes, and proof artifacts
- redaction, byte/token budgets, and replayable evidence by default

Avoid LLM-hostile defaults: verbose nested JSON in every prompt, raw logs,
screenshots, base64/binary/protobuf/gRPC payloads as model input, ad hoc
human-only debug text, broad polling, and hidden state that requires manual
inference. Extra context is allowed only when it pays for correctness, safety,
or observability that cannot be achieved through a cheaper lookup path.

## No Reactive Routing Monkey-Patches

Never repair model-routing failures by adding product-specific strings,
CSS selectors, DOM class names, filenames, or one-off lexical heuristics inside
server/runtime code such as `static_server.py`. That is reactive
monkey-patching: it hides missing architecture, increases token spend, and
guarantees future misses.

Routing knowledge must live in an owned contract: `docs/context/MAP.md`, the
nearest owning `AGENTS.md`/`README.md`, or a dedicated machine-readable route
registry with tests. Runtime code may load and enforce that contract, but must
not become the contract. If a request cannot be routed from declared surface,
owner, workspace root, capabilities, and proof policy, stop with
`route_contract_missing` or add the missing contract first. Do not dispatch
Hermes or any model to broad-search arbitrary roots as a substitute for route
ownership.

Hermes is a capability/tool provider, not the architecture owner. wasm-agent
must route, scope, budget, and verify work before invoking Hermes. Hermes must
receive a bounded task contract and should never be asked to infer the product
map from raw user text.

## Root-Cause Before Edge-Fix Law

After watching a failure, miss, or weak answer, do not propose a
product-specific, entity-specific, selector-specific, prompt-specific, or
file-specific fix as the next step until the architectural gap is named.

First classify the miss in owned-contract terms: missing route contract,
missing capability manifest, missing generic inspect/action/proof primitive,
missing runtime evidence, missing harness promise, or implementation bug in an
existing contract. The next step must repair or verify that contract layer.
Use the observed product/entity as a test fixture only after the generic
contract is named.

If the suggested fix would only help the exact observed case, it is reactive
programming even when no source code has been edited yet. Stop and restate the
generic capability or proof surface that would make future similar cases cheap,
bounded, and inspectable.

## Self-Improving Harness Loop

After intent/context routing and before slow investigation, rebuilds, runtime
control, or source edits, check whether repeated uncertainty is already covered
by `docs/context/HARNESS_PROMISES.json`. Use
`docs/context/HARNESS.md` as the contract for Harness Factory Reflection,
promise results, invalidation, and post-loop harvest.

Novel diagnosis can stay in the exploration lane. Repeated manual inference
must be harvested: the second repeat needs a promise candidate or a named block;
the third repeat must be promoted into the registry or blocked on missing
primitive/access/observability. Validate the registry with
`python3 tools/context/check-harness-promises.py`.

## Monolith Growth Guard

Known survival monoliths are frozen growth surfaces, not feature destinations:
`plugins/wasm-agent/public/app.js`,
`plugins/wasm-agent/server/static_server.py`,
`plugins/wasm-agent/public/styles.css`,
`scripts/public/clone/clone_manager.py`,
`native/windows/src/main.js`,
`native/android/app/src/main/java/com/colmeio/wasmagent/MainActivity.kt`, and
`plugins/wasm-agent/server/routes.py`.

Before editing one of these files, classify the change reason without broad
token spend: categorically decide whether the change must stay in the monolith
as bootstrap wiring, delegation, compatibility shim, or removal-only cleanup, or
whether it belongs in a new or existing owned module. Durable logic must move to
the module path first, then the monolith keeps only the shortest readable
delegation.

Shrink-on-touch is mandatory. Any non-exception patch that touches a frozen
monolith must include a small follow-up extraction/removal so the monolith has a
net line-count reduction in the same diff. If the touched concern cannot be
shrunk immediately, stop and add the missing module/contract, or carry a
temporary architecture exception with proof of why shrinkage is unsafe now.

Net shrink alone is not enough. Before adding any line to a frozen monolith,
check whether the durable logic can live in an existing owned module. If yes,
append to that module and leave only the shortest delegation/removal in the
monolith. If no module exists, create the smallest owned module first and then
delegate from the monolith. Only unavoidable bootstrap wiring, compatibility
shims, or removal-only cleanup may stay solely in the monolith without a paired
owned-module change.

Growth in a frozen monolith requires an added-line marker with owner, reason,
and expiry:
`ARCH_EXCEPTION: owner=<id>; reason=<why>; expires=YYYY-MM-DD`.
Temporary exceptions do not prove good architecture; they are debt markers to
remove. Run `python3 tools/context/check-monolith-growth.py` before finalizing
changes that touch frozen files. The guard must fail when frozen-file additions
lack a paired owned-module change or explicit exception; treat that failure as
a required refactor prompt rather than optional advice.

## Verified Loop-Aware Engineering

For meaningful native, bridge, wake-word, hot-op, runtime-control, release, or
rebuild-heavy work, use Verified Loop-Aware Engineering under Rule-of-Three
Prime Checkpoints.

- Start with loop reflection: can live introspection, HMR, hot-op, runtime
  config, feature flag, downloaded model/runtime, or diagnostics avoid or shrink
  the rebuild?
- Improve observability before rebuilding when a small status field, command
  result, counter, event, or watcher would make the next failure explainable.
- Do not let one agent self-authorize a shortcut. Separate the report into
  Builder intent, Watcher evidence, and Gatekeeper decision even when one Codex
  instance performs all three.
- Prefer three independent evidence classes when possible: static evidence,
  runtime evidence, and behavioral evidence.
- Keep prime checkpoints atomic, independent, falsifiable, observable, and
  non-redundant. Avoid vague checks like "looks good" or "compiled, so works."
- Record rebuild command, target, duration or approximate duration, validation
  command, proof inspected, and the next loop-shortening opportunity whenever a
  rebuild-heavy operation is performed.

### Command Isolation Guard

Parallelize discovery, serialize commitment.

Cheap read-only discovery may run in parallel: `rg`, `sed`, `git diff`,
`json.tool`, `wc`, small file reads, and tiny focused checks.

Any command that may exceed 10 seconds, mutate state, start a server, run a
full suite, build/install, contact a runtime/device/bridge, or produce proof
artifacts must run alone, never inside a parallel tool batch. Announce the
exact long/stateful command before starting it, wait for it to finish, and do
not start another tool call while it is running.

After any user interruption or aborted tool turn, check for leftover matching
processes before continuing. Report whether the interrupted command completed,
was aborted, or is still running before launching the next long/stateful
command.

## Final Response Next-Step Law

Every substantive final response must end with a first-grade `**Next Step:**`
line. This is an evolution control, not a courtesy footer.

The next step must name the single highest-leverage action that should happen
after the current answer. Prefer actions that shorten proof loops: a live
introspection/control command, a local deterministic check, a focused runtime
proof, or a harness promise promotion. If work is blocked, name the exact
missing access, primitive, or proof. Do not end with broad menus, vague
"let me know" language, or a rebuild/reinstall suggestion unless the missing
runtime proof or platform primitive makes that step necessary.

Never let a final answer imply completion just because code was written,
tests passed, or a build succeeded. State the verified level plainly, then
close with the next concrete evolution step.

## Context Routing

Use `/local/README.md` as the broad project context and `docs/context/` as the
canonical route/claim/verification layer. Before editing a durable boundary,
read the nearest child `AGENTS.md` when present:

- `/local/docs/context/README.md`
- `/local/plugins/wasm-agent/AGENTS.md`
- `/local/native/AGENTS.md`
- `/local/native/windows/AGENTS.md`
- `/local/native/android/AGENTS.md`
- `/local/docs/roadmap/AGENTS.md`
- `/local/scripts/public/AGENTS.md`
