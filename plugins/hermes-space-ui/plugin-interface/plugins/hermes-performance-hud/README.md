# Hermes Performance HUD Bundle

This bundle adds a small Hermes-owned runtime performance overlay to Space
Agent without editing Space Agent core files.

Install or sync it as a normal customware module:

```txt
L1/_all/mod/hermes/performance-hud/
```

The HUD uses the documented `_core/framework/head/end` HTML seam for its
stylesheet and `_core/framework/initializer.js/initialize/end` for runtime
setup. It shows approximate frame rate and browser memory when the current
runtime exposes `performance.memory`; otherwise memory is labeled `n/a`.

The visibility preference is stored in browser `localStorage` under
`hermes.performanceHud.enabled`. The bundle also publishes
`space.hermesPerformanceHud` and `window.hermesPerformanceHud` helpers with
`isEnabled()`, `setEnabled(value)`, and `toggle()`.

The bundle includes a compact Admin > Modules toggle adapter for any Modules
panel mounted in a Hermes-bundle-visible app context. Current Space Agent Admin
Mode clamps module resolution to `maxLayer=0`, so L1 Hermes bundles do not load
inside the real Admin page today. The final Admin > Modules toggle goal
therefore requires a generic upstream module-settings/action seam instead of a
Hermes core patch.

`scripts/start_space_agent.sh` syncs this bundle into the local
`SPACE_AGENT_CUSTOMWARE_PATH` so the overlay is reapplied after Space Agent
checkout updates.
