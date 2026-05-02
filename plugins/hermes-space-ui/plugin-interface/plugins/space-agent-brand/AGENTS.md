# AGENTS

## Purpose

`space-agent-brand/` owns the Hermes-specific Space Agent brand icon bundle.

It replaces browser and PWA icon metadata through the documented framework head
HTML seam while keeping Space Agent core untouched.

## Ownership

This folder owns:

- `space.bundle.yaml`: bundle metadata for the Hermes brand icon bundle.
- `site.webmanifest`: Hermes PWA icon manifest served from this module.
- `assets/source/hermes-space-ui-agent-nous.png`: durable source artwork copied
  out of volatile workspace storage.
- `assets/icons/`: optimized favicon, touch icon, and PWA icon derivatives.
- `ext/html/_core/framework/head/end/space-agent-brand.html`: declarative head
  tags that override the default Space Agent icons.
- `ext/js/_core/framework/initializer.js/initialize/end/space-agent-brand.js`:
  browser initializer hook that swaps late-mounted Space Agent avatar images.
- `space-agent-brand.css` and `space-agent-brand.js`: bundle-owned browser
  assets for icon presentation and late DOM application.

## Local Contracts

- Keep this mirror installable at `L1/<group>/mod/hermes/space-agent-brand/`.
- Runtime behavior must enter through `_core/framework/head/end` or
  `_core/framework/initializer.js/initialize/end`.
- Do not patch `server/pages/index.html`, `server/pages/enter.html`, or Space
  Agent packaging assets from this bundle.
- Regenerate derived files in `assets/icons/` when the source artwork changes.

## Development Guidance

- Prefer declarative head tags for browser/PWA icon changes.
- If Space Agent adds a native brand asset seam, move the bundle to that seam
  instead of editing Space Agent core files.
