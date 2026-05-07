# wasm-agent State

This directory is the gitignored local state root for the `wasm-agent` shadow
PWA server.

Expected local files include:

- `wasm-agent.pid`
- `wasm-agent.log`
- `db/sqlite/wa_db.sqlite3`, the local account database containing `user_tb`.
- `db/sqlite/wa_auth_secret`, the local signed-cookie secret. Keep this file
  private; rotating it signs out existing browser sessions.
- `browser/`, runtime Host Browser captures and profile data
- `users/<acc_id>/spaces/<space_id>/`, account-owned space metadata.
- `users/<acc_id>/device-settings.json`, the account's current main-device
  pointer for the Connected Devices flow.
- App positions, widget geometry, topology card positions, and space density
  are browser-local PWA state by default, not files under this server state
  root. Server-retained layout sync/backup is reserved for a future premium
  storage path.
- `users/<acc_id>/timelines/<space_id>/`, account/space-local Timeline
  metadata and automatic checkpoint fingerprint cache. The versioned Timeline
  module contract lives under `public/modules/timeline/`; these directories are
  only user/runtime data.
- `users/<acc_id>/devices/`, recently seen browser/device records used by the
  Home Connected Devices app. These are local account runtime records, not a
  security session list.
- `users/<acc_id>/device-sync/`, downloaded device-sync installer manifests and
  bootstrap status records.
- `users/<acc_id>/observation/latest.json`, the latest frontend observation
  debug snapshot published by the PWA for that account. This is local runtime
  state, not durable history.
- `users/<acc_id>/attachments/`, same-origin compact image assets and JSON
  metadata created for embedded assistant image-card turns. The server prunes
  this cache by byte, file-count, and age limits after saves. This is local
  runtime state and is not a durable media library.
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
