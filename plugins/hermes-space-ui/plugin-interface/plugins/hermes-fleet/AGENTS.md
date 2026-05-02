# AGENTS

## Purpose

`hermes-fleet/` owns the Hermes Fleet customware-bundle source mirror for Space Agent.

This bundle is the Hermes-specific consumer of the upstream Customware Bundle Interface. It should remain installable into Space Agent as a normal module and removable without runtime patches.

## Ownership

This folder owns:

- `space.bundle.yaml`: Hermes Fleet bundle manifest.
- `space-seed/`: installable Space Agent space/widget seed source for the local Hermes Fleet workspace.
- `ext/html`, `ext/js`, and top-level browser assets: Hermes Fleet UI adapters that consume Space Agent extension points.
- `README.md`: install, update, removal, and seam notes.

## Local Contracts

- The manifest may advertise Hermes actions and desired Space Agent extension points.
- Seeded space/widget files may call the local bridge with `space.fetchExternal(...)`.
- Node lifecycle UI must stay on documented bridge endpoints such as `GET /nodes`, `GET /nodes/{node_id}/stats`, `POST /nodes`, and `POST /nodes/{node_id}/action`.
- Executable actions must register through `space.bundles.actions` from loaded module code.
- External state must sync through `space.bundles.bridge`.
- Do not patch Space Agent private stores, page shells, or runtime files from this bundle.

## Development Guidance

- Add future UI through `ext/html` adapters and component files.
- Add future behavior through `ext/js` hooks and `space.extend(...)`.
- Add future agent guidance through `ext/skills/*/SKILL.md`.
- When Space Agent lacks a required seam, propose the generic upstream seam first and keep the Hermes-specific usage documented here.
