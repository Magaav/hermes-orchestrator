# Visão Vendas

Authenticated workspace for Visão Imóveis, using Go, SQLite WAL, Vite, React,
TypeScript, and PWA. Its first modules are Atendimento and Studio.

## Runtime

| Field | Value |
| --- | --- |
| Public URL | `https://visao.colmeio.com` |
| Local backend | `127.0.0.1:18083` |
| Frontend | React + Vite + TypeScript PWA |
| Backend | Go `net/http` |
| Persistence | SQLite WAL at `data/visao.sqlite3` |
| Attachments | Authenticated PDF-only uploads at `data/uploads` |
| Studio | Ephemeral property-photo treatment through Visão's Master:frontier envelope |
| Timezone | `America/Sao_Paulo` |

The MVP uses Google OAuth Authorization Code + PKCE and a server-side session.
Its ignored `app.env` points `GOOGLE_CREDENTIALS_FILE` at the Zaia e Cainelli
environment so both apps share one OAuth client without duplicating its secret.
Visão owns its callback URL and explicit allowed-email list. Never commit the
environment file or SQLite/upload contents: the workflow contains CPF,
identity, banking, and transaction data.

## Workspace modules

Home is the first authenticated page and loads no module data until a module is
opened.

- **Atendimento** owns the interactive version of
  `media/Checklist e Tratativas - Visão Vendas.pdf`. Attached PDFs open inside
  an authenticated same-origin modal instead of a new tab. One header action
  saves pending changes and streams every referenced PDF for that atendimento
  as a deterministic ZIP, without assembling the archive in browser memory.
- **Studio** accepts up to 50 JPEG, PNG, WebP, or AVIF photos of up to 20 MB
  each through one click/drag-and-drop target. It runs at most ten independent
  cleaning lanes, sends originals only through the authorized ephemeral
  datacenter request, preserves watermarks unless their removal is explicitly
  authorized, and builds the cleaned ZIP in the browser. Generated
  images cross the response boundary in ordered 8 KB NDJSON chunks and are
  assembled once in browser memory, avoiding one oversized frame and per-chunk
  React renders. A lazy browser Web Worker then converts each result to
  pixel-lossless AVIF before the card is marked complete; every file in the ZIP
  therefore ends in `.avif`. Clicking a completed card opens a browser-local
  Before/After comparison whose compact proof shows only the token use actually
  reported by Codex, without treating tokens as a currency quote. Every card
  has its own treatment clock, driven by one shared UI timer and frozen on
  completion or failure.
- **Configurações** owns persisted day/night, touch, and notification
  preferences; a metadata-only inventory of SQLite tables, project files, and
  media; an append-only CUD audit projection; and administration of login
  emails, hierarchical roles, and route capabilities. Admin separates role
  identity (**Cargos**) from capability assignment (**Ações**) and active login
  membership (**Usuários**).

Authorization is capability-based at the backend boundary. The session exposes
only the current user's compact role/capability set, Home hides unauthorized
modules, and each protected API route independently enforces its capability.
Bootstrap allowlist emails receive the immutable `Owner` role; new users
default to `Membro`. Custom roles stay below their creator's priority, cannot
edit or assign equal/higher roles, and cannot delegate `Owner`.
Administrative mutations use independent actions for managing lower roles,
assigning actions, inviting users, assigning lower roles, and revoking lower
users. An administrator can delegate only actions they already hold. Revoked
users remain in audit history but are omitted from the authorized-user list.

The topbar identity opens the current user's profile modal, where name, email,
roles, photo change, and logout stay together. A custom JPEG, PNG, or WebP photo
of up to 5 MB is stored as one private user-owned file under
`data/profile-pictures/`, with the Google account picture as fallback. Profile
reads and changes are capability-gated, and each change emits bounded audit
evidence without storing image bytes in SQLite.

The inventory counts files, bytes, tables, columns, and rows only on demand. It
does not return file contents, form payloads, photos, PDFs, session tokens, or
secrets. The CUD audit stores compact, bounded JSON evidence for future creates,
updates, and deletes across settings, access control, Atendimento uploads and
records, Studio treatments, sessions, and archived photos.

Successful batches are archived as user-owned Studio sessions. Each session
stores its original and lossless AVIF files under `data/studio-sessions/`, while
SQLite stores only ownership, timing, byte counts, trace links, and navigation
metadata. Authenticated routes protect both image variants. The history is
ordered newest-first, supports previous/next navigation, Before/After, and AVIF
ZIP recovery. Deleting a session removes its private files, metadata, and linked
usage rows.

After its first opening, one Studio instance remains mounted while the user
navigates between authenticated modules. Home and Atendimento only hide that
instance, so active lanes, selected browser files, timers, and archive writes
continue without duplicated state; returning to Studio reveals the same batch.
Only logout unmounts Studio and aborts remaining work.

Dashboard totals, averages, and series aggregate every provider-reported token
component, including partial reports, without inferring missing components.
Completeness remains explicit: partial records state that only confirmed
components are counted, while records with no reported usage stay outside the
metrics. The Studio Dashboard exposes this provider evidence for the current
user or everybody, with hourly points for a day, daily points for a month, and
monthly points for a year.

The request declares `wire_version: 2`. Tabs opened before the chunked contract
remain retry-compatible: a missing wire version receives the original terminal
result shape under the corrected Studio deadline, so selected browser-local
files are not discarded by a forced reload.

Studio owns its compact reconstruction contract and provider transport in
`backend/studio_master_frontier.py`. Each photo is sent in a
`visao.studio.master_frontier.envelope.v1` envelope whose public model identity
is `master:frontier`; the envelope is deterministically projected into one Codex
Responses request with one built-in image-edit action, avoiding a second model
call or duplicate image generation. The provider-model mapping is private to
the Visão backend. A result remains usable when Codex reports only the main
response usage, but its proof is marked partial and excluded from Dashboard
totals. The production path does not import, call, or require WASM Agent.

The square gear in Studio opens its settings. That screen uses the Codex
app-server device-code flow and reports the Codex account and runtime as
separate states. The same ChatGPT/Codex session authenticates the treatment;
Studio has no API-key field, route, file, or environment dependency.
“Datacenter operacional” appears only when the Codex session and runtime are
ready. Built-in image generation consumes the connected account's general
Codex usage limits.

## Atendimento flow

The original four-page paper/PDF form is represented as six interactive steps:

1. Atendimento identity.
2. Seller, buyer, legal-entity, and property document checklist with PDF upload.
3. Property registration.
4. Buyer, co-buyer, seller, and co-seller registration and banking data.
5. Transaction terms, financing, commission, possession, external partnership,
   and complementary notes.
6. Required-field/document review, print view, and final submission.

The UI keeps one form state tree and uses one 900 ms autosave timer. The backend
saves the complete payload and its compact list projection in one SQLite upsert.
That is the shortest observable path for this MVP and avoids duplicate section
state, API mutations, and render lifecycles.

## Commands

```bash
make build
make start
make verify
```

Development UI:

```bash
make start
make dev
```

Vite proxies `/api` to `127.0.0.1:18083`.

## API contract

| Route | Auth | Purpose |
| --- | --- | --- |
| `GET /healthz` | No | Process liveness |
| `GET /readyz` | No | SQLite readiness |
| `GET /api/version` | No | Compact version/capability report |
| `GET/DELETE /api/session` | Mixed | Session inspect/logout |
| `GET /auth/google/start` | No | Google OAuth + PKCE initiation |
| `GET /auth/google/callback` | No | One-time OAuth callback and session creation |
| `GET /api/schema` | Yes | Compact LLM-readable resources/actions/proof contract |
| `GET /api/profile/picture/{userID}` | Yes | Read the current user's private custom profile photo |
| `PUT /api/profile/picture` | Yes | Replace the current user's custom profile photo |
| `GET /api/submissions` | Yes | Recent compact form summaries |
| `POST /api/submissions` | Yes | Create/update draft or submit in one upsert |
| `GET /api/submissions/{id}` | Yes | Pull one full form payload on demand |
| `GET /api/submissions/{id}/documents` | Yes | Stream every referenced atendimento PDF as one ZIP |
| `POST /api/uploads` | Yes | Upload one PDF up to 20 MB |
| `GET /api/uploads/{id}` | Yes | View a protected PDF in the same-origin modal or download it |
| `GET /api/studio/status` | Yes | Redacted Codex account/runtime/datacenter readiness |
| `GET /api/studio/usage` | Yes | Personal/team token summaries for a navigable day, month, or year |
| `GET/POST /api/studio/sessions` | Yes | List or create a private Studio session |
| `GET/DELETE /api/studio/sessions/{id}` | Yes | Open or permanently remove one owned session |
| `POST /api/studio/sessions/{id}/photos` | Yes | Archive one treated original/AVIF pair with elapsed time |
| `GET /api/studio/sessions/{id}/photos/{photo}/{kind}` | Yes | Read one authenticated source or output image |
| `POST /api/studio/login/start` | Yes | Start a bounded Codex device-code login |
| `POST /api/studio/clean` | Yes | Stream one ephemeral property-photo treatment as NDJSON |

The server checks same-origin mutations, signs 30-day `HttpOnly` sessions,
stores one-time PKCE state in SQLite, rechecks the Google email allowlist on
every authenticated request, validates submit-required fields, and serves
uploaded PDFs and Studio session images only through authenticated routes.
Studio requests are limited to ten active workers. Session photos are accepted
only after their `trace_id` exists in the server-owned usage stream for the same
authenticated user; token values are never trusted from the browser.

The UI palette and SVG/PWA mark are derived from the supplied PDF contract:
Visão blue `#005596`, alert red `#d91a1a`, and its blue/red eye symbol.

## Editable PDF

`media/editavel.pdf` preserves the four original page designs and adds 139
named AcroForm fields over the printed blanks, checks, choices, and observation
lines. Field names reuse the interactive form contract where the paper form has
the same value, such as `buyer.cpf`, `property.registry`, and
`deal.depositMethod`; checklist controls use
`checklist.<group>.<document>.checked|notes`.
Blank widgets remain transparent so the source design is unchanged. Once a
text value is present, its inset white appearance masks only the dotted writing
guide behind the characters; check and radio appearances draw only their blue
mark inside the original printed target.

Regenerate and structurally verify the PDF with:

```bash
cd frontend
npm run pdf:editable
```

The blank-canvas V3 is generated independently at `media/editavel-v3.pdf`.
It uses only the Visão vector mark, wordmark, and palette; all page geometry,
input boxes, labels, and AcroForm widgets are newly drawn. Its eight-page
layout gives identity, contact, banking, financial, and narrative values the
width and height expected by their data type and rejects overlapping widget
rectangles during generation.

```bash
cd frontend
npm run pdf:editable:v3
```

The systemd unit runs with a `0027` umask, a read-only system view, no new
privileges, and a single writable path at `data/`. Studio keeps its dedicated
Codex credentials and runtime home under owner-only `data/studio-runtime/`; the
installed extension directory is bind-mounted read-only only for executable
discovery. Runtime secrets use mode `0600`;
SQLite/upload data uses owner/group-only modes.

The public Caddy route excludes the Studio image stream from compression and
uses low-latency proxy flushing. The Go server keeps its 30-second write
deadline for ordinary routes; only an active Studio treatment receives a
four-minute deadline, bounded above the three-minute provider timeout.

## Deployment

`deploy/visao.service` owns the process. `deploy/Caddyfile.visao` owns the host
route and reverse-proxies the public domain to the loopback-only application.
DNS must point `visao.colmeio.com` to this machine before Caddy can complete its
public certificate flow.

## Current verification status

`implemented-runtime-proven`: an authenticated allowed-account session,
Home/Atendimento, Studio settings, the square gear, desktop/mobile layout, and
the datacenter preflight were observed in production Chrome on 2026-07-30. A
real JPEG then completed through the public authenticated HTTP/2 route in 64.9
seconds using Visão's `master:frontier` envelope. The returned PNG replaced the
original card image, removed movable ladder/clutter, preserved room geometry,
and retained the watermark because its removal was not authorized. This proves
one production treatment.

The comparison and usage path was separately observed on the same date with
one real 94.9-second HTTP/2 treatment. Before/After switched between distinct
browser-local URLs and the old transport reported 4,102 main-model tokens, but
did not report image-generation input/output tokens. That record is now
correctly classified as partial and excluded from totals and averages. Day,
month, and year navigation had already been observed with 24, 31, and 12 graph
points respectively.

The lossless-AVIF delivery is source-tested, production-build proven, and
browser-proven against the live app. Chrome loaded the published lazy worker,
encoded and decoded an AVIF with `ftypavif`, and preserved all channels in the
deterministic fixture. The restored Codex-only transport completed another real
photo on 2026-07-30 and reached the Before/After modal after browser AVIF
conversion. Codex reported 3,859 input plus 229 output tokens for the main turn
(4,088 total) but no image-generation usage. The run is therefore visibly
partial and excluded from totals; five partial runs now contribute zero tokens
to Dashboard totals, with no estimate added.

Per-photo timing and Studio session memory are production-runtime proven on
2026-07-30. One real treatment froze at 82,653 ms, archived a private
81,809-byte JPEG source plus a 1,332,794-byte lossless AVIF, and reopened both
through authenticated `200` responses in the chronological history. A separate
empty-session lifecycle proof created, opened, navigated, deleted, and confirmed
the deleted id as `404`, with the session count returning to its initial value.

Build success is source/package proof only. Runtime acceptance requires:

1. `GET /healthz` and `GET /readyz` through the loopback service.
2. Public TLS and `/api/version` through `https://visao.colmeio.com` after DNS.
3. Browser Google login, new draft autosave, reopen, PDF upload/view, final submit, and
   print validation with representative non-production data.
4. Studio browser proof for 50-photo selection enforcement, one Codex-only real
   treatment with provider-reported usage inspection, watermark
   preservation/authorization behavior, lossless AVIF decode, and `.avif` ZIP
   export.
