# WASM Agent Native Guard

Binding workspace rules for `/local`.

Production WASM Agent Native is cloud-only.

Backend:
https://wa.colmeio.com

Production app URL:
https://wa.colmeio.com/home?native=electron

Localhost 127.0.0.1:8877 is dev-only and forbidden in production.

Never claim the Windows installer is fixed based on source tests or
`win-unpacked`. The final extracted NSIS installer and installed `app.asar`
must pass verification.

Windows login persistence also requires installed-app proof: Google login,
full close/reopen, `https://wa.colmeio.com/home?native=electron`,
`authCookie.hasWaUid: true`, durable cookie expiration metadata, and
authenticated `/auth/session`.

Build success is not runtime proof. Roadmap/future/proposal claims must not be
presented as current software.

## Context Routing

Use `/local/README.md` as the broad project context and `docs/context/` as the
canonical route/claim/verification layer. Before editing a durable boundary,
read the nearest child `AGENTS.md` when present:

- `/local/docs/context/README.md`
- `/local/plugins/wasm-agent/AGENTS.md`
- `/local/native/AGENTS.md`
- `/local/native/windows/AGENTS.md`
- `/local/native/android/AGENTS.md`
- `/local/docs/roadmap/AGENTS.md`
- `/local/scripts/public/AGENTS.md`
