# wasm-agent Private Beta Launch

This is the launch runbook for the first joinable `wasm-agent` private beta.
The goal is secure access for a small allowlist while keeping infrastructure
simple: Caddy terminates HTTPS, the Python server stays loopback-only, and
Hermes bridge/node power remains admin-only.

## Launch Shape

- Public edge: `https://wa.colmeio.com` through Caddy or the current HTTPS
  reverse proxy.
- App process: `plugins/wasm-agent/server/static_server.py` on
  `127.0.0.1:8877`.
- Bridge target: Hermes Space UI bridge on `127.0.0.1:8790`.
- Identity: Google OAuth web client whose authorized JavaScript origin matches
  the public HTTPS origin.
- Access: `ADMIN_EMAIL` for admins, `USER_EMAILS` for the small private beta
  allowlist.

Do not expose ports `8877` or `8790` directly to the internet. Public traffic
must reach wasm-agent only through the HTTPS reverse proxy.

## Environment

Configure `plugins/wasm-agent/conf/wa.env` or equivalent process environment:

```bash
GOOGLE_LOGIN_CLIENT_ID=<google-web-client-id>
ADMIN_EMAIL=admin@example.com
USER_EMAILS=user1@example.com,user2@example.com
HERMES_WASM_AGENT_PUBLIC_ORIGIN=https://wa.colmeio.com
```

The app creates and uses:

- `state/db/sqlite/wa_db.sqlite3` for allowed Google account rows;
- `state/db/sqlite/wa_auth_secret` for signed session cookies;
- `state/users/<acc_id>/` for account-local spaces, devices, timelines, and
  attachments;
- `state/security-loop/` for the Admin security-loop dashboard.

Keep `wa.env`, `wa_db.sqlite3`, and `wa_auth_secret` private. Rotating
`wa_auth_secret` signs out current browsers.

## Start, Stop, Check

```bash
/local/plugins/wasm-agent/scripts/start_wasm_agent.sh
/local/plugins/wasm-agent/scripts/doctor.sh
/local/plugins/wasm-agent/scripts/stop_wasm_agent.sh
```

Before inviting users, verify:

- HTTPS login shell loads from the public origin.
- Admin signs in and sees `space-admin`.
- Standard allowlisted user signs in and does not see Admin, bridge, browser,
  node action, or Security surfaces.
- New Space, Devices, Artifacts, Modules, and Config work for standard users.
- `doctor.sh` passes on the host.

## Backup And Rollback

Before a beta invite or risky change:

```bash
tar -C /local/plugins/wasm-agent -czf /local/plugins/wasm-agent/state/wasm-agent-state-backup-$(date -u +%Y%m%dT%H%M%SZ).tgz state
```

Rollback is intentionally boring:

1. Stop wasm-agent.
2. Restore the previous source checkout and state backup if needed.
3. Start wasm-agent.
4. Run `doctor.sh`.
5. Verify admin login and one standard-user login.

## Hermes Attack/Defense Loop

The first security loop uses two platform-level Hermes nodes:

- `hermes-attack`: runs bounded probes against owned surfaces.
- `hermes-defense`: turns findings into human-gated mitigation plans or
  PR-ready patch plans.

These nodes are not wasm-specific. They should evolve into general platform
security actors for wasm-agent, Hermes bridge, node lifecycle, plugins, browser
harnesses, storage, auth, marketplace artifacts, and future account/tenant
boundaries.

`hermes-attack` MVP scope:

- auth gates and role separation;
- protected route access;
- same-origin bridge allowlist;
- service worker and cache freshness;
- storage import/export handling;
- path traversal attempts;
- attachment access;
- browser private-network blocking;
- config leakage.

Out of scope for MVP:

- credential brute force;
- DDoS or rate-pressure testing;
- third-party targets;
- uncontrolled public scanning.

`hermes-defense` MVP scope:

- propose mitigations;
- propose tests;
- propose docs updates;
- create PR-ready plans on request.

Defense does not silently apply production changes. Browser dashboard actions
are human-gated.

## Security Dashboard Contract

The Admin-only `Security` panel and `Security Loop` widget read:

- `GET /security-loop/status`
- `GET /security-loop/findings`

The frontend polls the loop every few seconds while the Security panel or
Security Loop widget is open; WebSocket/SSE streaming is not required for the
private-beta MVP.

Admins can append findings and decisions:

- `POST /security-loop/findings`
- `POST /security-loop/findings/{id}/decision`

Finding records use `hermes.security_loop.finding.v1`:

```json
{
  "schema": "hermes.security_loop.finding.v1",
  "source_node": "hermes-attack",
  "target_surface": "auth",
  "category": "role-separation",
  "severity": "critical",
  "confidence": 0.9,
  "exploitability": 0.8,
  "summary": "Standard user reached an admin route.",
  "evidence_preview": "Short redacted evidence only.",
  "task_id": "task_123",
  "proposed_action": "Require admin role before bridge proxy."
}
```

Statuses are `new`, `triaged`, `accepted`, `rejected`, `mitigating`,
`resolved`, and `watching`. The dashboard sorts by score first, then most
recent update. Raw logs should stay in linked tasks/log surfaces; the dashboard
uses concise redacted evidence previews.

## Invite Gate

Invite the first small allowlist only when:

- the HTTPS origin and Google OAuth origin match;
- admin and standard-user roles are verified;
- protected/admin routes fail closed for standard users;
- bridge routes are allowlisted;
- backup/rollback has been exercised or reviewed;
- `hermes-attack` bounded probes show no unresolved critical finding;
- `hermes-defense` can produce at least one human-gated remediation plan from a
  test finding.
