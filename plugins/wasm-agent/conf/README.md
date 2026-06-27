# wasm-agent Private Configuration

`wa.env` is the machine-local security configuration for wasm-agent. It must not
be committed to the repository.

Create it from the example:

```bash
cp plugins/wasm-agent/conf/wa.env.example plugins/wasm-agent/conf/wa.env
```

Then set the Google admin account, optional standard-user allowlist, and the
Google Identity Services web client id:

```env
ADMIN_EMAIL=admin@example.com
USER_EMAILS=user1@example.com,user2@example.com
GOOGLE_LOGIN_CLIENT_ID=your-google-web-client-id.apps.googleusercontent.com
```

Optional `Master:frontier` direct OpenAI receiver:

```env
WASM_AGENT_MASTER_FRONTIER_RECEIVER=openai-responses
WASM_AGENT_OPENAI_MODEL=gpt-5.5
WASM_AGENT_OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=sk-...
```

With that receiver enabled, avatar-chat `Master:frontier` envelopes are sent
directly to the OpenAI Responses API from the wasm-agent backend. The browser
does not store or forward the OpenAI key.

Optional ChatGPT/Codex OAuth receiver:

```env
WASM_AGENT_MASTER_FRONTIER_RECEIVER=openai-codex
WASM_AGENT_CODEX_MODEL=gpt-5.5
WASM_AGENT_CODEX_BASE_URL=https://chatgpt.com/backend-api/codex
WASM_AGENT_CODEX_AUTH_JSON=/home/ubuntu/.hermes/auth.json
```

With `openai-codex`, the backend reads a server-side ChatGPT/Codex OAuth access
token from `WASM_AGENT_CODEX_ACCESS_TOKEN`, `OPENAI_CODEX_ACCESS_TOKEN`, the
configured auth JSON, `~/.hermes/auth.json`, or `~/.codex/auth.json`. The token
is never sent to the browser. Token refresh remains owned by the Hermes/Codex
login flow; if the stored token expires, wasm-agent returns a typed
`missing-codex-oauth`/auth diagnostic and the operator should re-run the
Hermes/Codex login. `WASM_AGENT_CODEX_BASE_URL` may be either
`https://chatgpt.com/backend-api/codex` or the full
`https://chatgpt.com/backend-api/codex/responses`; wasm-agent normalizes both
to one `/responses` request path.

Security rules:

- `ADMIN_EMAIL` is required for unlimited admin access. If both `ADMIN_EMAIL`
  and `USER_EMAILS` are absent or empty, every Google account is rejected.
- `USER_EMAILS` is an optional comma-separated allowlist for standard accounts.
  Standard accounts receive isolated state roots under
  `state/users/<acc_id>/` and the 1 GB user storage quota.
- `GOOGLE_LOGIN_CLIENT_ID` is required for the Google sign-in button to render.
- `OPENAI_API_KEY` is optional, but required if `Master:frontier` should use
  the direct OpenAI Responses receiver.
- `WASM_AGENT_CODEX_AUTH_JSON` is optional, but recommended if
  `Master:frontier` should use ChatGPT/Codex OAuth through `openai-codex`.
- Keep `wa.env` readable only by trusted local operators.
- Use a Google OAuth web client whose authorized JavaScript origins include the
  deployed origin, for example `https://wa.colmeio.com`.
- Public traffic should reach wasm-agent only through the HTTPS reverse proxy;
  the Python app should stay bound to `127.0.0.1`.

The server also accepts process environment overrides for deployment systems:
`HERMES_WASM_AGENT_ENV_PATH` for relocating this private env file, and
`HERMES_WASM_AGENT_GOOGLE_CLIENT_ID` for emergency client-id override. The
normal source of truth for admins, standard users, and Google client id is
`wa.env`.

Bridge lifecycle uses process environment rather than `wa.env` by default:
`HERMES_WASM_AGENT_BRIDGE_HOST`, `HERMES_WASM_AGENT_BRIDGE_PORT`,
`HERMES_WASM_AGENT_BRIDGE_STATE_DIR`, and
`HERMES_WASM_AGENT_BRIDGE_TOKEN`.

For wasm-agent-cloud/private instances, set
`HERMES_WASM_AGENT_DEPLOYMENT_MODE=cloud` and point
`HERMES_WASM_AGENT_CLOUD_STATE_ROOT` at a private deployment root outside the
public repo. In that mode the default env path becomes `<cloud-root>/conf/wa.env`
and the server refuses public plugin state paths for secrets or user data.
