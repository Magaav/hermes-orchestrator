# Hermes Space Plugin Interface

This folder is the Hermes-side source mirror for Space Agent customware bundles.

Installable bundle source lives under `plugins/`. Copy or sync one bundle into a normal Space Agent customware module root:

```txt
L1/<group>/mod/<author>/<repo>/
L2/<user>/mod/<author>/<repo>/
```

The upstream Space Agent PR should stay generic. Hermes-specific behavior belongs here and should enter Space Agent only through documented seams: `space.bundle.yaml`, `ext/html`, `ext/js`, `ext/skills`, `space.extend(...)`, `space.bundles.actions`, and `space.bundles.bridge`.

`bridge.js` is a tiny helper for bundle code that wants to register Hermes actions or sync external bridge state without touching private Space Agent runtime internals.

`plugins/component-context-menu/` mirrors the upstreamable Component Context Menu bundle. Install it at `L1/<group>/mod/space/component-context-menu/` or `L2/<user>/mod/space/component-context-menu/` to add a right-click Space widget menu with a footer `Copy ID` action. `scripts/start_space_agent.sh` syncs it into `L1/_all/mod/space/component-context-menu` for Hermes Space UI.

`plugins/space-agent-brand/` carries the Hermes-specific browser and PWA icon override. Install it at `L1/<group>/mod/hermes/space-agent-brand/`; `scripts/start_space_agent.sh` syncs it into the local customware root so it is reapplied after Space Agent checkout updates.

`plugins/hermes-performance-hud/` carries the Hermes FPS/memory overlay. Install it at `L1/<group>/mod/hermes/performance-hud/`; `scripts/start_space_agent.sh` syncs it into the local customware root. It exposes browser helpers for toggling visibility now, while the final Admin > Modules toggle requires a generic Space Agent module-settings seam because Admin Mode currently clamps custom module resolution to `maxLayer=0`.

`package.json` marks this folder as ESM so the helper can use the same `export` syntax expected by Space Agent browser modules.
