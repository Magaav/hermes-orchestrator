# wasm-agent State

This directory is the gitignored local state root for the `wasm-agent` shadow
PWA server.

Expected local files include:

- `wasm-agent.pid`
- `wasm-agent.log`
- `browser/`, runtime Host Browser captures and profile data
- `observation/latest.json`, the latest frontend observation debug snapshot
  published by the PWA. This is local runtime state, not durable history.
- `attachments/`, same-origin compact image assets and JSON metadata created
  for embedded assistant image-card turns. The server prunes this cache by
  byte, file-count, and age limits after saves. This is local runtime state and
  is not a durable media library.
- Image-card analyzer modules cache loaded functions in browser memory only;
  their module contracts live under `public/modules/` and do not create durable
  state here by default.
- `timeline/`, local Timeline checkpoint metadata and the automatic checkpoint
  fingerprint cache. The versioned Timeline module contract lives under
  `public/modules/timeline/`; this directory is only per-user/runtime data.

Do not store source code, generated app bundles, secrets, or durable product
docs here. Versioned module firmware belongs under
`/local/plugins/wasm-agent/public/modules`, other versioned code belongs under
`/local/plugins/wasm-agent`, and roadmap intent belongs under
`/local/docs/roadmap/space-os`.
