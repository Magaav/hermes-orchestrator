# wasm-agent-cloud Foundation

This page records the current client-first production foundation for shared
spaces, chat, and future wasm-agent-cloud instances.

## Current Contract

- The public repo ships the factory: PWA shell, local server, module firmware,
  CLI backup support, tests, and docs.
- Production user data belongs outside the public repo. In
  `HERMES_WASM_AGENT_DEPLOYMENT_MODE=cloud`, the server requires
  `HERMES_WASM_AGENT_CLOUD_STATE_ROOT` and rejects public plugin state paths.
- The default cloud private layout is `<cloud-root>/state` for runtime data,
  `<cloud-root>/state/db/sqlite` for account/friend/sync/fleet metadata, and
  `<cloud-root>/conf/wa.env` for private deployment configuration.
- `horc space backup` archives the active wasm-agent state root into
  `/local/backups` with a manifest and excludes browser caches, logs, pid files,
  symlinks, and other noisy runtime files.

## Client-First Runtime

The browser is the primary runtime owner. It keeps workspace layout, WIS state,
chat sessions, direct-provider/model preferences, and client artifacts local by
default. The `client-state` core module provides the IndexedDB-first browser
storage contract with an in-memory fallback.

The backend stays narrow:

- account authentication and signed sessions
- friendship lookup, pending inbound/outbound state, accept/decline/cancel, and
  accepted-friend removal
- shared-space membership, live presence, and bounded room events
- lightweight `/sync/events` rows for accepted-friend direct chat and shared
  collaboration cursors
- metadata-only `/fleet` records plus explicit main-node reservation
- optional backup through `horc space backup`

Backend Hermes node provisioning remains an explicit heavy/premium action. The
current `/fleet/nodes/ensure-main` endpoint reserves ownership metadata only; it
does not spawn a worker by itself.

## Chat and People

The embedded chat drawer now has a People toggle beside the `Chat` title. The
People view combines `/account/friends` with current shared-space members from
`/spaces/room`. Users can add people by id or email, see inbound and outbound
pending requests without refreshing through a bounded poll, accept or decline
incoming requests, cancel outgoing requests, remove accepted friends, and open a
direct chat with accepted friends.

Direct chat is client-first. Browser sessions store the transcript locally, then
mirror text messages, built-in sticker messages, and emoji reaction events as
bounded `/sync/events` in a conversation whose members are the accepted friends.
The People button and friend rows show unread state, opening a conversation
marks it read locally, and message/friend events create deduped toast/ring
feedback. Attachments are represented as local metadata in this foundation
pass.

IndexedDB is the fast local source of truth for cached friends, pending
requests, recent direct conversations, unread counts, sync cursors, and direct
messages. If IndexedDB is unavailable, the client uses an in-memory store. The
current message cache is capped to the last 500 messages per conversation.

This realtime layer is still intentionally simple: it uses a bounded poll
instead of a websocket service, does not autoplay sound, and does not yet sync
shared-space room chat history beyond the existing room event contract.

## Safety Boundary

The cloud boundary is intentionally conservative:

- Cloud mode fails closed if state, database, auth secret, or env paths resolve
  inside the public plugin root.
- Dynamic friend/sync/fleet/account reads are excluded from service-worker
  caching.
- Public repo backups do not include private cloud state unless an operator
  explicitly points `horc space backup` at that private root.
- User database contents and cloud instance state are out of scope for public
  source commits.

## Next Work

- Add encrypted export/import for browser-local client-state snapshots.
- Add shared-space chat history polling and conflict cursors over `/sync/events`.
- Add websocket or server-sent event fanout only after the bounded poll has real
  usage evidence and quota needs.
- Add provider secret handling that keeps direct provider keys in browser or a
  private user vault, never in public repo defaults.
- Turn fleet metadata reservation into quota-gated, audit-logged Hermes node
  provisioning for premium deployments.
- Add restore verification for `horc space backup` archives before relying on
  them as production backups.
