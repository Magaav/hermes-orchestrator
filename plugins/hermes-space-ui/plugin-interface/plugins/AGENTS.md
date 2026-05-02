# AGENTS

## Purpose

`plugin-interface/plugins/` owns installable Hermes customware-bundle source folders.

Each child folder should map cleanly to one Space Agent module root after sync or copy into `L1/<group>/mod/<author>/<repo>/` or `L2/<user>/mod/<author>/<repo>/`.

## Ownership

Current bundles:

- `component-context-menu/`: generic Space Agent component context-menu bundle mirrored from the upstream PR fixture; it right-clicks Space widget cards through the Customware Bundle Interface and keeps `Copy ID` available for agent-targeted edits.
- `hermes-fleet/`: Hermes Fleet control bundle manifest and reference source.
- `space-agent-brand/`: Hermes browser/PWA icon bundle that overrides Space Agent head metadata through the framework head seam.

## Local Contracts

- Every bundle folder must include its own `AGENTS.md` and `space.bundle.yaml`.
- Bundle folders must be removable without leaving hidden runtime hooks behind.
- Keep Hermes-specific code here, not in the Space Agent upstream PR.
- Generic bundles mirrored from Space Agent PR fixtures should remain source-compatible with their upstream install path unless this plugin documents a local divergence.

## Development Guidance

- Prefer additive extension files and runtime action registration over exact-path overrides.
- Document any requested upstream seam in the bundle folder before relying on it.
