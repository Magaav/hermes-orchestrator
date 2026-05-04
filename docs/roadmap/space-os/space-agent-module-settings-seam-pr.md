# Space Agent Module Settings Seam PR Plan

Date: 2026-05-04

This is the upstreamable PR shape Hermes needs before product-specific controls
such as the Performance HUD toggle can live correctly in Admin > Modules.

## Goal

Add a generic, safe module settings/action surface to Space Agent without
letting arbitrary L1/L2 module JavaScript execute inside Admin Mode.

## Current Constraint

Admin Mode intentionally runs with `space-max-layer=0`. That keeps Admin UI
loaded from trusted L0 core modules only, but it also means Hermes-owned L1
customware cannot inject controls into Admin > Modules.

Hermes should not patch that core page locally just to add product controls.
Instead, Space Agent needs a core-owned seam that reads module metadata and
renders safe settings/actions in Admin.

## Proposed Server APIs

Add narrow APIs alongside the existing module endpoints:

- `module_settings_schema`
- `module_settings_get`
- `module_settings_set`
- `module_enable`
- `module_disable`

Behavior:

- reuse the existing module path normalization and permission checks from
  `server/lib/customware/module_manage.js`
- read declarative settings metadata from module-owned manifests without
  executing module JavaScript in Admin Mode
- store per-user settings under the caller's `L2/<user>/conf/modules/...`
  unless the schema declares an admin/global scope and the caller has admin
  write access
- publish mutations through the same tracked mutation flow used by module
  install/remove
- report effective enable/disable state through `module_info` and
  `module_list`

## Proposed Manifest Shape

Allow modules to declare Admin-safe settings in `space.bundle.yaml` or in a
layered metadata file such as:

```txt
ext/admin/module-settings/<setting-id>.yaml
```

Example:

```yaml
id: performance-hud
module: hermes/performance-hud
scope: user
fields:
  - id: enabled
    type: boolean
    label: Performance HUD
    default: true
```

Core Admin UI renders supported primitive controls only. Arbitrary module HTML
or JS should not run in Admin Mode.

## Proposed Admin UI

Extend Admin > Modules with a core-owned action/settings area per module:

- show effective enabled/disabled state when available
- render boolean, select, number, and text settings from sanitized schema
- save through `module_settings_set`
- disable unsupported field types rather than executing module code
- keep repository/open/remove actions as they work today

## Hermes Consumer Plan

After the upstream seam exists:

- move Hermes Performance HUD visibility from localStorage-only behavior to the
  new settings API, with localStorage as a client cache/fallback
- remove selector-based Admin Modules toggle attachment from
  `hermes-performance-hud`
- declare the HUD `enabled` field in a module settings manifest
- keep all Hermes UI source under
  `/local/plugins/hermes-space-ui/plugin-interface/plugins/hermes-performance-hud`

## Verification

The upstream PR should include tests for:

- schema discovery from L1 and L2 modules without Admin executing custom module
  JavaScript
- permission checks for user and admin/global settings scopes
- mutation tracking after settings writes
- module list/info reporting enable state
- Admin UI rendering a boolean setting and persisting a change

## Stop Rule

Do not locally patch Space Agent Admin Mode for Hermes-only controls unless this
generic seam is rejected upstream and the roadmap is explicitly updated with the
new fork risk.
