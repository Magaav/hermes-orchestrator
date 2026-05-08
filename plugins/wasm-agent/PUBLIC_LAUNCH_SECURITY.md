# wasm-agent Public Launch Security Gate

This checklist is the launch gate for exposing `wasm-agent` beyond a trusted
local network. A clean `hermes-attack` run is useful evidence, but public launch
also needs independent static checks, route-gate checks, browser/PWA hardening,
and staging verification.

Run the local gate:

```bash
/local/plugins/wasm-agent/scripts/public_launch_security_check.sh
```

Optionally point it at a staging deployment:

```bash
HERMES_WASM_AGENT_PUBLIC_URL=https://staging.example.com \
  /local/plugins/wasm-agent/scripts/public_launch_security_check.sh
```

## Launch Blockers

- Only the `wasm-agent` web origin is public. Do not expose the Hermes bridge,
  node API, CDP/browser-control backend, sqlite state, logs, or plugin state
  directories directly.
- HTTPS is terminated before any real public traffic. Auth cookies must be
  `HttpOnly`, `SameSite=Lax`, and `Secure` on public HTTPS origins.
- Public unauthenticated requests can load only the shell/static assets and
  login/session bootstrap. Bridge, browser, security-loop, agent, observation,
  timeline, logs, and node-action endpoints must require authentication and the
  required admin role.
- State-changing non-public `POST` routes must reject cross-origin requests.
- Browser streaming WebSockets must require same-origin `Origin`.
- Public responses must not advertise permissive wildcard CORS for the app
  origin. Prefer no CORS header unless a specific trusted origin is required.
- Request body limits must be in place for uploads, browser input, agent
  attachments, and security-loop writes.
- Service worker and browser caches must not cache auth/session, bridge,
  browser, security-loop, agent, observation, or attachment responses.
- Host Browser/CDP must be isolated from internal networks and credentials. If
  that isolation is not complete, disable the Host Browser module for public
  launch.
- Public HTTPS deployments disable Host Browser by default. Any opt-in via
  `HERMES_WASM_AGENT_BROWSER_ENABLED=1` must include attached CDP and
  private-network isolation evidence.
- Admin-only capabilities need a kill switch: Host Browser, node actions,
  bridge prompt submission, security-loop decisions, and agent attachments must
  be quickly disableable during an incident.

## Required Local Checks

- `scripts/doctor.sh` passes.
- `tests/wasm_agent_smoke.test.js` passes.
- `tests/ui_navigation_history.test.js` passes.
- `tests/security_loop_policy.test.py` passes.
- `tests/security_loop_runner.test.py` passes.
- JavaScript syntax check passes for `public/app.js`.
- Route policy tests prove:
  - `/bridge/*` is admin-only.
  - `/browser/*` is admin-only.
  - `/security-loop/*` is admin-only.
  - bridge proxy allowlist rejects absolute URLs and traversal paths.
  - browser WebSocket rejects missing or cross-origin `Origin`.

## Independent Scans

Run these on the launch branch or staging image. Missing tools are not a pass;
record them as launch follow-ups.

- Secret scan: `gitleaks` or `trufflehog`.
- Python/static scan: `bandit` and `semgrep`.
- Dependency scan: `pip-audit` and `osv-scanner`.
- Browser DAST against staging: OWASP ZAP baseline or full scan.
- TLS/header scan against staging: Mozilla Observatory, securityheaders.com, or
  equivalent.

## Manual Staging Tests

Use fake data and non-production credentials.

- Unauthenticated visitor:
  - Can load the shell and login flow.
  - Cannot read `/bridge/nodes`, `/security-loop/status`,
    `/agent/attachments/*`, `/observation/latest`, `/timeline/status`, or
    browser-control endpoints.
- Authenticated non-admin:
  - Can use user-owned Home/space features.
  - Cannot open Admin, bridge, browser, security-loop, timeline, node actions,
    logs, or agent-control routes.
- Admin:
  - Can use intended Admin routes.
  - Every node action, security-loop decision, browser-control request, and
    bridge prompt is visible in audit logs.
- Session abuse:
  - Forged, empty, expired, or stale cookies fail closed.
  - Cross-origin `POST` and WebSocket attempts fail.
- Abuse inputs:
  - Encoded traversal, absolute URLs, oversized JSON bodies, slow uploads, and
    high-rate requests are rejected or rate limited.
- PWA/browser:
  - Service worker does not cache sensitive API responses.
  - Sensitive routes are not readable from another origin.
  - Host Browser cannot reach metadata services or private control-plane hosts.

## Launch Evidence

Before public launch, attach or link:

- Latest `public_launch_security_check.sh` output.
- Latest `hermes-attack` run id and surfaces tested.
- Secret scan result.
- Static/dependency scan results.
- ZAP or equivalent staging report.
- TLS/header scan report.
- Manual staging checklist notes with tester/date.
