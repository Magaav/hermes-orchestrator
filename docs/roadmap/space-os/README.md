# Space OS Roadmap

This track is the continuity point for evolving Hermes Orchestrator, Hermes Space UI, and Space Agent into a cloud/progressive OS.

## Current State

- Hermes Orchestrator is the host-level control plane. `horc` and the clone manager remain the operational source of truth for node lifecycle, logs, backups, updates, and Guard integration.
- `/local/plugins/hermes-space-ui` is an external Hermes Orchestrator plugin. It starts a local Space Agent PWA on port `8787`, starts a Hermes bridge on port `8790`, and translates Space Agent UI actions into safe Hermes Orchestrator operations.
- `/local/plugins/wasm-agent` is a new shadow Hermes Orchestrator plugin. It serves a WASM-first installable PWA shell on port `8877`, uses the existing Hermes bridge on port `8790`, and lets the team compare the old Space UI path and new WASM UI path side by side.
- The standalone app/client surface has been pruned from this repo. Product UI and client work must stay under `/local/plugins`, with `/local/plugins/hermes-space-ui` as the current Space Agent UI path and `/local/plugins/wasm-agent` as the shadow WASM parity path.
- Hermes Space UI currently seeds Space Agent customware/module content into the generated customware root under `/local/plugins/hermes-space-ui/state/space-customware`. The launcher syncs `space-agent-brand` to `L1/_all/mod/hermes/space-agent-brand`, syncs `hermes-fleet` to `L1/_all/mod/hermes/fleet`, writes the Hermes Space UI skill under `L1/_all/mod/hermes/space_ui`, and seeds the `hermes-os` space, widgets, and LLM config under `L2/user`.
- Hermes Space UI now also syncs `hermes-performance-hud` to `L1/_all/mod/hermes/performance-hud`. This plugin-owned bundle adds the current FPS/memory overlay without editing Space Agent core. It exposes browser toggle helpers now; the final Admin > Modules toggle requires a generic Space Agent module-settings seam because Admin Mode clamps module resolution to `maxLayer=0`.
- `plugin-interface/plugins/component-context-menu` is source-owned and upstreamable. Hermes Space UI now syncs it to `L1/_all/mod/space/component-context-menu` so the right-click widget context menu is intentional runtime behavior instead of generated residue.
- Space Agent already has a layered module/customware model (`L0`, `L1`, `L2`) and an Admin > Modules surface. The current local evidence shows module list/remove/info/install APIs exist, while richer Hermes-specific module settings and enable/disable behavior still need generic seams before relying on that UI as a full management surface.
- Space Agent includes a browser surface module with `<x-browser>`. The current PWA/browser path is not a completed arbitrary browser-inside-browser engine without iframe. Native/Electron paths are more capable, and the PWA path must not be described as full browser parity today.
- The browser-engine feasibility spike in `browser-engine-feasibility-spike.md` marks PWA-only local WASM arbitrary browsing as no-go for v1. That result still applies to arbitrary external websites, but the active product wedge is now narrower: prove a WASM-first Hermes UI parity shell before revisiting browser infrastructure.
- `wasm-agent-parity-spike.md` records the new implementation direction: copy the useful Hermes UI output first, keep `hermes-space-ui` unchanged, serve the shadow PWA on a separate port, and move toward GPU-oriented/agent-readable WASM runtime contracts only after visible parity exists. `wasm-agent` module firmware now lives under `/local/plugins/wasm-agent/public/modules`, while per-user/runtime data stays under `/local/plugins/wasm-agent/state`.
- `embedded-agent-path.md` records the new parallel path: place a configurable embedded agent inside the visual workspace so it can talk with the user from there and observe user-visible actions through explicit observation/action contracts. Phase 1 now exists as the `wasm-agent` Observation inspector with app-local, session-only semantic analytics. Phase 2 now includes the global embedded assistant, compact tool context, automatic Timeline recovery points, and browser-built image cards for text-only provider compatibility.
- Current Hermes Space UI limitations are documented in `/local/plugins/hermes-space-ui/README.md`: no websocket/SSE log streaming yet, task submission requires a reachable Hermes API server, auth is a single shared token, bridge policy is a fixed allowlist, and rollback-aware planning is future work.

## Active Resume Branch

As of 2026-05-05, resume Space OS work from the **WASM harness saga**.

The browser-engine saga remains useful background evidence: PWA-only arbitrary
external browsing is still a no-go for v1, while the Host Browser stream proves
host-rendered browser pixels and bounded input can enter the workspace. The
main execution branch is now the `wasm-agent` harness: Home spaces, module
firmware, Host Browser stream, Observation inspector, embedded assistant,
Timeline checkpoints, and compact image-card perception. Future agents should
extend this harness before reopening broad browser-engine or cloud-domain work.

## Future Intent

- Serve an installable client from `https://space.colmeio.com`.
- Add Colmeio account login and cloud-backed user spaces so users can install/open the PWA from many devices and regain their spaces.
- Keep Hermes Agent and Space Agent future-proof by using extension systems first:
  - Hermes Agent: plugins, skills, tools, hooks, and components.
  - Space Agent: modules, customware bundles, extension points, widget runtimes, and components.
- Treat unavoidable core changes as upstream-seam design work. If a goal requires risky Hermes Agent or Space Agent core patching, stop and draft the smallest upstreamable PR before local implementation continues.
- Build a WASM-first Hermes UI/runtime shell as the near-term product wedge. The first goal is parity with current useful Hermes UI output, not arbitrary external browsing.
- Keep browser-like execution as a later Space OS capability. The high-risk arbitrary browser path must use remote browser infrastructure, native desktop capabilities, or a narrowed generated-app sandbox; it is not current behavior.
- In parallel, build toward a configurable embedded agent that inhabits the visual workspace. It should observe structured workspace/browser/fleet state and propose bounded actions through confirmation-first contracts.

## Pre-Evolution Gate

Do not start major Hermes Space UI, WASM browser runtime, Space OS cloud client, or product-surface implementation until docs match the current software.

Gate status on 2026-05-04: frozen for the current repo snapshot. Future code
CRUD must keep this gate true by updating docs in the same change.

The gate stays complete only when:

- Root, roadmap, plugin, script, and high-value folder docs describe current behavior.
- Future claims are labeled as roadmap, future work, proposal, risk, or open question.
- Legacy, partial, broken, deprecated, or experimental capabilities are labeled honestly.
- Generated/upstream/runtime folders are documented at parent level only.
- A future agent can answer "what should we do now?" from this roadmap and linked READMEs.

## Next Actions

1. Keep the product-surface rule frozen in every new change: no standalone app/client tree and no script-owned UI gateway. Product UI belongs under `/local/plugins`, currently through Hermes Space UI and the shadow `wasm-agent` parity plugin.
2. Evolve `wasm-agent` as the active harness: run it on port `8877`, keep `hermes-space-ui` on port `8787`, reuse the bridge on port `8790`, and document which surfaces have parity.
3. Harden the embedded assistant path around compact context: keep image cards, observation snapshots, transcript clipping, and Timeline recovery visible in the action chain before adding mutation tools.
4. Continue hardening the remote-cloud-browser-harness inside `wasm-agent`: domain changes, CPU throttling, frame health, and browser action reliability. The request/response CDP path now has bounded stale target cleanup through an idle session TTL.
5. Continue evolving the local module management surface in `wasm-agent`: the UI can switch Dev HMR, Observation, Host Browser, Timeline, Embedded Assistant, and image-card analyzer modules in browser local storage. Module firmware lives under `public/modules`; later work should connect these descriptors to explicit module contracts before they control backend lifecycle.
6. Validate lazy image-card analyzer evidence with real images, then move hot pixel work into small WASM modules only after the browser Canvas analyzer proves useful and stable.
7. Add remaining activity/Guard state parity to `wasm-agent` before moving cloud/PWA domain work forward.
8. Define the first WASM state/action/observation ABI only after the basic fleet/task/UI harness is visibly usable.
9. Use `space-agent-module-settings-seam-pr.md` as the upstreamable Space Agent PR plan when Space Agent module settings are needed again.
10. Keep generated-app WASM sandbox work separate from arbitrary external web browsing.
11. Revisit the remote browser proof after the WASM UI parity shell is proven or rejected. If remote browser work fails, stop Space OS browser product work again and revisit architecture before cloud/PWA rollout.
12. Use `operator-actions.md` as the human-side checklist for domain routing, TLS, auth, space sync, and remote browser infrastructure.

## Stop/Go Criteria

The WASM browser-engine path may proceed only if a spike can demonstrate enough of the following to justify continued investment:

- navigation and network loading
- visual rendering into a Space widget surface
- JavaScript execution for realistic app/site behavior
- input events such as click, type, and scroll
- an agent-readable snapshot or DOM-like/accessibility-like state
- screenshot or pixel capture
- isolation from the parent Space Agent page
- performance data sufficient to compare against iframe, native, or remote-browser options

If these cannot be demonstrated, stop local implementation and update this roadmap with the actual result before choosing a remote-browser, native-app, iframe-backed, or narrower generated-app-only approach.

## Resume Instructions

When context is lost, read these in order:

1. `/local/README.md`, especially Prompt Guidelines and Documentation Sync.
2. `/local/docs/roadmap/README.md`.
3. This file.
4. `/local/plugins/wasm-agent/README.md`.
5. `/local/plugins/wasm-agent/DESIGN.md`.
6. `/local/docs/roadmap/space-os/wasm-agent-parity-spike.md`.
7. `/local/docs/roadmap/space-os/embedded-agent-path.md`.
8. `/local/docs/roadmap/space-os/browser-engine-feasibility-spike.md`.
9. `/local/docs/roadmap/space-os/space-agent-seams.md`.
10. `/local/docs/roadmap/space-os/space-agent-module-settings-seam-pr.md`.
11. `/local/docs/roadmap/space-os/operator-actions.md`.
12. `/local/plugins/hermes-space-ui/README.md`.
13. `/local/plugins/hermes-space-ui/plugin-interface/README.md`.
14. `/local/plugins/hermes-space-ui/plugin-interface/plugins/README.md`.
15. `/local/plugins/hermes-space-ui/state/README.md`.

Then inspect current code before changing docs or implementation. Runtime/codeflow truth wins over stale documentation.

## Purpose Guardrails

- Do not let Space OS work become a private fork by default.
- Do not patch Hermes Agent or Space Agent core for product-specific behavior when a plugin/module/component seam can do the job.
- Do not reintroduce standalone product UI outside `/local/plugins`; Hermes Space UI is the current product client path.
- Do not mutate `hermes-space-ui` while developing the `wasm-agent` parity spike; compare the two surfaces side by side until a migration plan is documented.
- Do not let the embedded agent path bypass the browser harness or bridge safety model; it must receive structured observations and request bounded actions through explicit contracts.
- Do not describe future PWA, cloud login, or WASM browser behavior as shipped until it exists in code and has been verified.
- Keep the roadmap honest enough that a future agent can recover direction without re-litigating old assumptions.
