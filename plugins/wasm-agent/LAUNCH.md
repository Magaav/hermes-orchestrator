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
/local/plugins/wasm-agent/scripts/public_launch_security_check.sh
/local/plugins/wasm-agent/scripts/stop_wasm_agent.sh
```

Before inviting users, verify:

- HTTPS login shell loads from the public origin.
- Admin signs in and sees `space-admin`.
- Standard allowlisted user signs in and does not see Admin, bridge, browser,
  node action, or Security surfaces.
- New Space, Devices, Artifacts, Modules, and Config work for standard users.
- Host Browser WebSocket streams reject missing or cross-origin `Origin`
  headers before the upgrade.
- Host Browser remains disabled on the public HTTPS deployment unless
  `HERMES_WASM_AGENT_BROWSER_ENABLED=1` is set with attached CDP and
  private-network isolation evidence.
- `doctor.sh` passes on the host.
- `public_launch_security_check.sh` passes locally, and the same script is run
  with `HERMES_WASM_AGENT_PUBLIC_URL` against staging before public traffic.
- External secret, static-analysis, dependency, ZAP/DAST, and TLS/header scan
  reports are attached to the launch evidence listed in
  [`PUBLIC_LAUNCH_SECURITY.md`](./PUBLIC_LAUNCH_SECURITY.md).

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

The host-owned automation entrypoint is:

```bash
/local/plugins/wasm-agent/scripts/security_loop_run.py
```

It runs deterministic local probes, writes failed probes into
`state/security-loop/`, submits bounded `hermes-attack` tasks directly to each
node's Hermes Runs API, and asks `hermes-defense` for mitigation plans when
concrete findings exist. Use `--mode probes` for local checks only,
`--mode nodes` for Hermes-node tasks only, `--wait-sec 120` to poll node task
output and ingest JSON findings, and `--dry-run` to inspect the planned prompts
without writing state or queueing tasks. Native runs that are still active after
the wait deadline are marked `timeout` and stopped through
`/v1/runs/{run_id}/stop`. `--delivery bridge` is available only for legacy
compatibility.

For continuous host-owned auditing, start the sequential loop:

```bash
/local/plugins/wasm-agent/scripts/security_loop_auto_start.sh
```

It runs one `security_loop_run.py` execution at a time, waits for it to finish,
then sleeps before the next pass. Defaults are `--mode all`, a 300 second node
wait, and a 300 second interval. Tune with
`HERMES_WASM_AGENT_SECURITY_WAIT_SEC`,
`HERMES_WASM_AGENT_SECURITY_INTERVAL_SEC`,
`HERMES_WASM_AGENT_SECURITY_MODE`, and
`HERMES_WASM_AGENT_SECURITY_SURFACES`. The runner also takes a lock, so a manual
run will skip instead of overlapping an active loop run. To avoid recursive
spend, identical clean node audits stop after
`HERMES_WASM_AGENT_SECURITY_MAX_CLEAN_REPEAT` passes, default `3`, unless a
manual run uses `--force-node-task`. Stop it with:

```bash
/local/plugins/wasm-agent/scripts/security_loop_auto_stop.sh
```

In the UI, open the Admin Security Loop widget or the Admin `Security` side
panel. The latest-run card shows runner status and Hermes-node task status even
when the findings queue is empty. A clean audit is valuable only as regression
evidence; remediation value starts when a probe or `hermes-attack` produces a
concrete finding that can be accepted, rejected, watched, or sent to
`hermes-defense`.

In the Topology widget, wasm-agent now reads each live node's native status and
stats. `hermes-attack` and `hermes-defense` should report
`opencode-go/deepseek-v4-flash` when their env files are configured with
`HERMES_INFERENCE_PROVIDER=opencode-go` and
`API_SERVER_MODEL_NAME=deepseek-v4-flash`. Right-click a topology node and choose
`Statistics` to open a live balloon with token consumption, sessions, cost,
activity, tool calls, warnings/errors, a smoothed token chart, and recent
activity. The stats balloon is draggable, and changing the `hour`, `daily`,
`weekly`, or `monthly` window keeps it open. The `hour` window filters the last
hour from the supported daily sample set so operators can feel whether the node
is alive now. A node whose latest security runner execution is still active and
has an active task, or whose token count is moving, is shown as `working`
instead of merely `idle` or `online`; stale task rows from completed runs do not
make the orchestrator yellow.

The Security Loop widget and panel also show run history from
`GET /security-loop/runs`. Each entry summarizes what `hermes-attack` tested,
task status, findings, token/API deltas, and the value verdict. The runner feeds
`hermes-attack` a host-collected authenticated route map using a local allowed
admin session, but it withholds cookies and tokens from the model.

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
- browser-stream WebSocket origin checks are active;
- Host Browser is disabled publicly, or its explicit public opt-in has attached
  CDP/private-network isolation evidence;
- backup/rollback has been exercised or reviewed;
- `hermes-attack` bounded probes show no unresolved critical finding;
- `hermes-defense` can produce at least one human-gated remediation plan from a
  test finding.
