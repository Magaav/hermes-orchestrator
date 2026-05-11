# Space OS Operator Actions

Date: 2026-05-04

These are actions the human/operator must eventually complete outside the repo
to connect the Space OS product surface.

## Domain And Network

- Point `space.colmeio.com` to the host or edge that will serve the Space Agent
  PWA.
- Put TLS in front of the PWA; service workers, install prompts, browser
  storage, and many modern web APIs expect a secure context outside localhost.
- Decide whether the public edge terminates directly on Space Agent or on a
  reverse proxy that routes:
  - PWA/static app traffic
  - wasm-agent bridge traffic
  - future remote browser streaming/control traffic
- Keep VM-local bridge endpoints private by default. Public routes should go
  through explicit authenticated proxy rules, not expose `127.0.0.1:8790`
  semantics directly.

## Identity And Spaces

- Choose the first login provider and account model for Colmeio spaces.
- Decide how local Space Agent `L2/<user>` spaces map to cloud-backed Colmeio
  accounts.
- Define backup/export/import expectations before moving user spaces into
  hosted storage.
- Define tenant boundaries for Hermes Orchestrator nodes, Space Agent users,
  and remote browser sessions.

## Remote Browser Infrastructure

- Provision an isolated environment for remote Chromium sessions.
- Define per-session limits for CPU, memory, disk, lifetime, network egress,
  and concurrent tabs.
- Decide how pixels stream to the PWA widget: screenshot polling, WebSocket
  image frames, WebRTC, or another transport.
- Decide how Hermes receives page state: DOM snapshot, accessibility tree,
  screenshot, network log, console log, or a reduced merged snapshot.
- Define secrets/cookie isolation and cleanup rules before handling real user
  browsing sessions.

## Deployment Checks

- Verify PWA installability from `https://space.colmeio.com`.
- Verify service worker scope and cache invalidation.
- Verify bridge authentication and public CORS rules.
- Verify remote browser isolation under failure and timeout.
- Verify logs do not leak browser secrets, auth tokens, or page content beyond
  intended retention.

## Current Blockers

- PWA-only local WASM arbitrary browsing failed the v1 feasibility gate.
- Admin > Modules cannot render Hermes L1 module settings until Space Agent has
  a generic module-settings/action seam.
- Cloud account login and cloud-backed space sync are not implemented yet.
