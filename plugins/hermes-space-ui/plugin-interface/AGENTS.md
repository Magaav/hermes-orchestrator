# AGENTS

## Purpose

`plugin-interface/` owns the Hermes-side source mirror for Space Agent customware bundles.

This folder is the place to keep Hermes-specific bundle manifests, bridge helpers, and future extension files that install into Space Agent. It mirrors the upstream Customware Bundle Interface without adding Hermes code to Space Agent core.

## Ownership

This folder owns:

- `README.md`: how the mirror maps into Space Agent customware roots.
- `package.json`: declares this helper folder as ESM so browser-style bridge modules are syntax-checkable locally.
- `bridge.js`: small browser-side helper for wiring Hermes bundle code to `space.bundles`.
- `plugins/`: installable Hermes bundle source folders.

## Local Contracts

- Source here may be copied or synced into `L1/<group>/mod/<author>/<repo>/` or `L2/<user>/mod/<author>/<repo>/`.
- Bundle code must use documented Space Agent seams such as `ext/html`, `ext/js`, `ext/skills`, `space.extend(...)`, `space.bundles.actions`, and `space.bundles.bridge`.
- Do not use this folder for monkey patches, runtime injections, or edits against private Space Agent files.

## Development Guidance

- Keep each bundle under `plugins/<bundle>/` documented with its own `AGENTS.md`.
- When a needed seam is missing, describe the upstream seam in the bundle docs before adding any local workaround.
