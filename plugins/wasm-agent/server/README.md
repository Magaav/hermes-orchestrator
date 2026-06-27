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

`POST /agent/provider/envelope` and
`POST /agent/provider/envelope/stream` are the compact LLM-native head lanes
for admin avatar-chat and related embedded-agent decisions. They intentionally
bypass the Hermes turn/session context and send only a bounded envelope to the
configured receiver. Non-admin users must stay on the existing bridge/provider
chat path.

The envelope must include `objective`. Preferred fields are `trace_id`,
`compact_state`, `capabilities`, `constraints`, `evidence_refs`,
`allowed_actions`, `action_schemas`, `budget`, and `output_schema`. Secrets in
the provider-proxy path are redacted before prompt assembly. With
`receiver=openai-responses`, the stream route starts a durable direct-head
worker, sends the raw envelope directly to the OpenAI Responses API using
`OPENAI_API_KEY` or `WASM_AGENT_OPENAI_API_KEY` from the process environment or
`wa.env`, and stores only compact redacted run events including replayable
`head.delta` chunks. With `receiver=openai-codex`, the same durable worker uses
server-side ChatGPT/Codex OAuth credentials from `WASM_AGENT_CODEX_ACCESS_TOKEN`,
`OPENAI_CODEX_ACCESS_TOKEN`, `WASM_AGENT_CODEX_AUTH_JSON`, `~/.hermes/auth.json`,
or `~/.codex/auth.json`, then streams to
`https://chatgpt.com/backend-api/codex/responses` with Codex-compatible headers.
The browser never receives the OAuth token, and token refresh remains the
responsibility of the Hermes/Codex login flow. If the direct head returns a
validated `dispatch.hermes` action, wasm-agent dispatches it through the
existing bridge/Runs API surface and records compact
`hermes.dispatch`/progress/final proof. Run replay streams compact trace actions
for envelope, head decision, Hermes dispatch, touched files, changed files,
tests, and proof events. These routes bypass context, not admin gating, auth,
provider routing, diagnostics, or account gating.

Direct-head routes that can dispatch tool or source work must preserve the same
post-turn audit contract as `/agent/session/message`: capture before/after
worktree state, return `changed_files`, include timeline checkpoint diagnostics,
and emit changed-file/proof run events. The UI already renders diff and
Stepback from that payload; do not replace it with a text-only proof summary.
