# Space OS Roadmap

This track is the continuity point for evolving Hermes Orchestrator, Hermes Space UI, and Space Agent into a cloud/progressive OS.

## Current State

- Hermes Orchestrator is the host-level control plane. `horc` and the clone manager remain the operational source of truth for node lifecycle, logs, backups, updates, and Guard integration.
- `/local/plugins/hermes-space-ui` is an external Hermes Orchestrator plugin. It starts a local Space Agent PWA on port `8787`, starts a Hermes bridge on port `8790`, and translates Space Agent UI actions into safe Hermes Orchestrator operations.
- The standalone app/client surface has been pruned from this repo. Product UI and client work must stay under `/local/plugins`, with `/local/plugins/hermes-space-ui` as the active Space UI path.
- Hermes Space UI currently seeds Space Agent customware/module content into the generated customware root under `/local/plugins/hermes-space-ui/state/space-customware`. The launcher syncs `space-agent-brand` to `L1/_all/mod/hermes/space-agent-brand`, syncs `hermes-fleet` to `L1/_all/mod/hermes/fleet`, writes the Hermes Space UI skill under `L1/_all/mod/hermes/space_ui`, and seeds the `hermes-os` space, widgets, and LLM config under `L2/user`.
- Hermes Space UI now also syncs `hermes-performance-hud` to `L1/_all/mod/hermes/performance-hud`. This plugin-owned bundle adds the current FPS/memory overlay without editing Space Agent core. It exposes browser toggle helpers now; the final Admin > Modules toggle requires a generic Space Agent module-settings seam because Admin Mode clamps module resolution to `maxLayer=0`.
- `plugin-interface/plugins/component-context-menu` is source-owned and upstreamable, but it is not currently synced by the Hermes Space UI launcher. A generated runtime copy may still exist under `state/space-customware` from earlier experiments; decide whether to adopt it into startup sync or prune the runtime residue before treating it as intended active behavior.
- Space Agent already has a layered module/customware model (`L0`, `L1`, `L2`) and an Admin > Modules surface. The current local evidence shows module list/remove/info/install APIs exist, while richer Hermes-specific module settings and enable/disable behavior still need generic seams before relying on that UI as a full management surface.
- Space Agent includes a browser surface module with `<x-browser>`. The current PWA/browser path is not a completed arbitrary browser-inside-browser engine without iframe. Native/Electron paths are more capable, and the PWA path must not be described as full browser parity today.
- Current Hermes Space UI limitations are documented in `/local/plugins/hermes-space-ui/README.md`: no websocket/SSE log streaming yet, task submission requires a reachable Hermes API server, auth is a single shared token, bridge policy is a fixed allowlist, and rollback-aware planning is future work.

## Future Intent

- Serve an installable client from `https://space.colmeio.com`.
- Add Colmeio account login and cloud-backed user spaces so users can install/open the PWA from many devices and regain their spaces.
- Keep Hermes Agent and Space Agent future-proof by using extension systems first:
  - Hermes Agent: plugins, skills, tools, hooks, and components.
  - Space Agent: modules, customware bundles, extension points, widget runtimes, and components.
- Treat unavoidable core changes as upstream-seam design work. If a goal requires risky Hermes Agent or Space Agent core patching, stop and draft the smallest upstreamable PR before local implementation continues.
- Build a Hermes-controlled WASM browser-engine/sandbox runtime as a v1 product requirement. The goal is browser-like execution inside widgets without iframe as the primary runtime, with agent-visible state and control. This is high-risk R&D and not current behavior.

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

1. Keep the product-surface rule frozen in every new change: no standalone app/client tree and no script-owned UI gateway. Product UI belongs under `/local/plugins`, currently through Hermes Space UI.
2. Use `space-agent-module-settings-seam-pr.md` as the upstreamable Space Agent PR plan for module settings, module-owned Admin actions, enable/disable state, widget runtime registration, and performance telemetry.
3. Decide the current status of `component-context-menu`: startup-synced runtime bundle, manual module install candidate, upstream PR fixture, or retired reference. Prune any generated runtime residue if it is not adopted.
4. Run a focused WASM browser-engine feasibility spike before product implementation:
   - load and render one arbitrary external site without iframe as the primary runtime
   - render one generated Hermes app in a widget sandbox
   - expose inspectable state and input control to Hermes
5. If the spike fails the stop/go criteria, revisit architecture before building the cloud product surface.
6. If the spike passes, design the Space OS cloud/PWA client plan around verified Space Agent seams, not core patches.

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
4. `/local/docs/roadmap/space-os/space-agent-seams.md`.
5. `/local/docs/roadmap/space-os/space-agent-module-settings-seam-pr.md`.
6. `/local/plugins/hermes-space-ui/README.md`.
7. `/local/plugins/hermes-space-ui/plugin-interface/README.md`.
8. `/local/plugins/hermes-space-ui/plugin-interface/plugins/README.md`.
9. `/local/plugins/hermes-space-ui/state/README.md`.

Then inspect current code before changing docs or implementation. Runtime/codeflow truth wins over stale documentation.

## Purpose Guardrails

- Do not let Space OS work become a private fork by default.
- Do not patch Hermes Agent or Space Agent core for product-specific behavior when a plugin/module/component seam can do the job.
- Do not reintroduce standalone product UI outside `/local/plugins`; Hermes Space UI is the current product client path.
- Do not describe future PWA, cloud login, or WASM browser behavior as shipped until it exists in code and has been verified.
- Keep the roadmap honest enough that a future agent can recover direction without re-litigating old assumptions.
