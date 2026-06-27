# wasm-agent Server

`server/` owns both local Python processes used by `wasm-agent`.

- `static_server.py`: account-gated PWA/backend server on `0.0.0.0:8877`
  through `scripts/start_wasm_agent.sh` by default, with
  `HERMES_WASM_AGENT_HOST` available to override the bind address.
- `bridge.py`: wasm-agent-owned Hermes bridge on `127.0.0.1:8790`.
- `routes.py`, `schemas.py`, and `auth.py`: bridge route, schema, and token
  helpers for fleet/node state, resources, logs, lifecycle actions, task
  submission, and host resource summaries.

The bridge routes requests through the Hermes Orchestrator CLI/API boundary.
It must not import Hermes Agent internals or patch runtime node state directly.

## LLM-Native Direct Envelope

`POST /agent/provider/envelope` is the compact LLM-native head lane for admin
avatar-chat and related embedded-agent decisions. It intentionally bypasses the
Hermes turn/session context and sends only a bounded envelope to the configured
provider through the existing account-gated backend proxy. Non-admin users must
stay on the existing bridge/provider chat path.

The envelope must include `objective`. Preferred fields are `trace_id`,
`compact_state`, `capabilities`, `constraints`, `evidence_refs`,
`allowed_actions`, `action_schemas`, `budget`, and `output_schema`. Secrets in
the envelope are redacted before prompt assembly. This route bypasses context,
not admin gating, auth, provider routing, diagnostics, or account gating.
