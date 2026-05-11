# Space Agent Seam Audit

Date: 2026-05-04

This historical note records the 2026-05-04 read-only inspection of the
generated Space Agent checkout that existed before the wasm-agent bridge
migration. Do not recreate or edit a generated Space Agent checkout for current
Hermes product work.

## Current Module APIs

Space Agent exposes these module endpoints:

- `module_list`
- `module_info`
- `module_install`
- `module_remove`

They are implemented by `server/api/module_*.js` and delegate to
`server/lib/customware/module_manage.js`.

Current behavior:

- module roots must live under `L1/<group>/mod/<author>/<repo>/` or
  `L2/<user>/mod/<author>/<repo>/`
- list areas include `l1`, `l2_self`, `l2_user`, and `l2_users`
- cross-user and aggregated user-layer listings require admin access
- install clones or updates a Git repository into the requested writable module
  path
- remove deletes the writable module path
- module writes reuse Space Agent app-file permission rules and mutation
  tracking
- module info resolves effective installed locations through layered
  customware inheritance

## Current Extension Seams

Space Agent customware modules can use documented extension surfaces:

- `space.bundle.yaml` for module metadata
- `ext/html/...` with `<x-extension>` anchors
- `ext/js/...` with `space.extend(...)` hook points
- `ext/skills/...` for agent-facing skills
- layered `/mod/<author>/<repo>/...` asset resolution through `L0`, `L1`, and
  `L2`

The retired Space Agent integration used these seams for:

- `hermes/space-agent-brand`
- `hermes/fleet`
- `hermes/performance-hud`
- `space/component-context-menu`

`space/component-context-menu` was adopted into launcher sync after the audit,
so the generated runtime copy was intentional behavior in that retired path.

## Current Admin Modules UI

The Admin > Modules panel lists installed modules, filters by area/search,
opens repository URLs, and removes writable non-aggregated modules.

Admin Mode currently sets `meta name="space-max-layer" content="0"`, so L1/L2
customware does not load inside the real Admin page. This is a sensible core
safety boundary, but it means Hermes L1 bundles cannot directly inject Admin >
Modules controls today.

Current gap:

- no formal module settings seam
- no generic module enable/disable state
- no module-owned Admin > Modules action injection point
- no widget runtime registration API surfaced through Admin > Modules
- no performance telemetry settings API

Hermes Performance HUD therefore cannot truthfully satisfy the final Admin >
Modules toggle requirement through L1 customware alone. It exposes browser
toggle helpers now, and the Admin control should be implemented through a
formal Space Agent module-settings/action seam when one exists.

## Current Browser Runtime

Space Agent has a substantial `_core/web_browsing` module with:

- `<x-browser>` surfaces
- `space.browser` helpers for open, navigate, inspect, evaluate, click, type,
  submit, and scroll
- packaged desktop support through Electron webview/native bridge paths
- an ordinary browser/PWA fallback that uses iframe and warns that embedded
  browsing works in native desktop apps for now

This does not satisfy the Space OS v1 requirement for iframe-free arbitrary
browser-inside-browser behavior in a PWA. The next browser step is still a
feasibility spike for a WASM or remote/native architecture, not product
implementation.

## Upstreamable Seam Proposal Targets

Before more Hermes product behavior attaches to Space Agent Admin > Modules,
draft the smallest upstreamable Space Agent PR shape for:

- module settings metadata and storage
- module-owned Admin > Modules actions or settings panels
- enable/disable state for modules
- widget runtime registration
- performance telemetry preference/state exposure

Hermes product code should consume generic seams from a current plugin-owned
interface, not patch Space Agent core locally.
