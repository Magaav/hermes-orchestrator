# wasm-agent State

This directory is the gitignored local-development state root for the
`wasm-agent` PWA server and local bridge.

In `HERMES_WASM_AGENT_DEPLOYMENT_MODE=cloud`, production/user data must live
outside the public repo under `HERMES_WASM_AGENT_CLOUD_STATE_ROOT`. In that mode
the server refuses to use `/local/plugins/wasm-agent/state`, and the default
private layout is:

- `<cloud-root>/state/`, account, sync, shared-space, attachment, and runtime state.
- `<cloud-root>/state/db/sqlite/wa_db.sqlite3`, account/friend/sync/fleet metadata.
- `<cloud-root>/state/db/sqlite/wa_auth_secret`, signed-cookie secret.
- `<cloud-root>/conf/wa.env`, private deployment configuration.

Expected local files include:

- `wasm-agent.pid`
- `wasm-agent.log`
- `bridge/bridge.pid` and `bridge/bridge.log`, the wasm-agent-owned Hermes
  bridge process state for `127.0.0.1:8790`.
- `db/sqlite/wa_db.sqlite3`, the local account database containing `user_tb`,
  friendship lifecycle metadata, lightweight sync event rows for accepted direct
  chats and shared-space collaboration cursors, account fleet ownership
  metadata, Flux credit ledger rows, and instance audit records for grants and
  provisioning attempts.
- `db/sqlite/wa_auth_secret`, the local signed-cookie secret. Keep this file
  private; rotating it signs out existing browser sessions.
- `browser/`, runtime Host Browser captures and profile data
- `users/<acc_id>/spaces/<space_id>/`, account-owned space metadata.
- `users/<acc_id>/device-settings.json`, the account's current main-device
  pointer for the Connected Devices flow.
- App positions, widget geometry, topology card positions, Space area, and
  Space distance are browser-local PWA state by default, not files under this
  server state root. Server-retained layout sync/backup is reserved for a
  future premium storage path.
- People/direct-chat caches are browser-local by default: friends, pending
  requests, unread counts, direct conversations, shared-space group
  conversations, sync cursors, stickers, reactions, and the last 500 cached
  messages per conversation live in IndexedDB when available, with an in-memory
  fallback.
- Encrypted client-state exports are user-downloaded JSON snapshots of those
  browser-local stores. The passphrase stays in the browser, and the snapshot is
  not server state unless an operator or user explicitly stores it outside the
  repo.
- `users/<acc_id>/timelines/<space_id>/`, account/space-local Timeline
  metadata and automatic checkpoint fingerprint cache. The versioned Timeline
  module contract lives under `public/modules/timeline/`; these directories are
  only user/runtime data.
- `users/<acc_id>/devices/`, recently seen browser/device records used by the
  Home Connected Devices app. These are local account runtime records, not a
  security session list.
- `users/<acc_id>/device-sync/`, downloaded device-sync installer manifests and
  bootstrap status records.
- `shared-spaces/<shared_space_id>/`, shared-space metadata, live presence, and
  bounded room events. This is a relay/sync surface, not the default owner of
  browser-local app layout.
- `users/<acc_id>/observation/latest.json`, the latest frontend observation
  debug snapshot published by the PWA for that account. This is local runtime
  state, not durable history.
- `users/<acc_id>/attachments/`, same-origin compact image assets and JSON
  metadata created for embedded assistant image-card turns. The server prunes
  this cache by byte, file-count, and age limits after saves. This is local
  runtime state and is not a durable media library.
- `security-loop/`, append-only finding events plus a compact current summary
  for the Admin-only `hermes-attack` / `hermes-defense` dashboard. It stores
  redacted evidence previews and decisions, not raw attack logs.
- Image-card analyzer modules cache loaded functions in browser memory only;
  their module contracts live under `public/modules/` and do not create durable
  state here by default.
- Standard users are limited to 1 GB under `users/<acc_id>/`; admin accounts are
  unlimited.

Do not store source code, generated app bundles, secrets, or durable product
docs here. Versioned module firmware belongs under
`/local/plugins/wasm-agent/public/modules`, other versioned code belongs under
`/local/plugins/wasm-agent`, and roadmap intent belongs under
`/local/docs/roadmap/space-os`.
