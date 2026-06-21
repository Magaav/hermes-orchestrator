# WASM Agent Native Guard

Binding workspace rules for `/local`.

Production WASM Agent Native is cloud-only.

Backend:
https://wa.colmeio.com

Production app URL:
https://wa.colmeio.com/home?native=electron

Localhost 127.0.0.1:8877 is dev-only and forbidden in production.

Current Android device ADB is only reachable through the installed Windows
bridge. Codex/cloud-local `adb devices` is expected to be empty and must not be
treated as Android-disconnected evidence for the wake loop. Use Windows bridge
hot ops/native-control for ADB-backed Android work unless the user explicitly
changes the physical setup.

Never claim the Windows installer is fixed based on source tests or
`win-unpacked`. The final extracted NSIS installer and installed `app.asar`
must pass verification.

Windows login persistence also requires installed-app proof: Google login,
full close/reopen, `https://wa.colmeio.com/home?native=electron`,
`authCookie.hasWaUid: true`, durable cookie expiration metadata, and
authenticated `/auth/session`.

Build success is not runtime proof. Roadmap/future/proposal claims must not be
presented as current software.

## Verified Loop-Aware Engineering

For meaningful native, bridge, wake-word, hot-op, runtime-control, release, or
rebuild-heavy work, use Verified Loop-Aware Engineering under Rule-of-Three
Prime Checkpoints.

- Start with loop reflection: can live introspection, HMR, hot-op, runtime
  config, feature flag, downloaded model/runtime, or diagnostics avoid or shrink
  the rebuild?
- Improve observability before rebuilding when a small status field, command
  result, counter, event, or watcher would make the next failure explainable.
- Do not let one agent self-authorize a shortcut. Separate the report into
  Builder intent, Watcher evidence, and Gatekeeper decision even when one Codex
  instance performs all three.
- Prefer three independent evidence classes when possible: static evidence,
  runtime evidence, and behavioral evidence.
- Keep prime checkpoints atomic, independent, falsifiable, observable, and
  non-redundant. Avoid vague checks like "looks good" or "compiled, so works."
- Record rebuild command, target, duration or approximate duration, validation
  command, proof inspected, and the next loop-shortening opportunity whenever a
  rebuild-heavy operation is performed.

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
