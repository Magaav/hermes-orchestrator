# Shared Voice Room Lifecycle

## Recovery Status

The production shared-space voice UI remains frozen as the integration target
and is disabled by default in `/config.json`. Set
`HERMES_WASM_AGENT_SHARED_VOICE_ENABLED=1` only when intentionally testing the
old production path or a later lab-derived port. The isolated `/voice-lab`
route is the current proof surface. It uses a
lab-only room store under `state/voice-lab/`, a page-scoped voice participant id,
and the existing shared voice signal schema so the signaling rules can be
validated before the full shared-space UI is enabled again.

## Current Production Failure Report

Inspection target:

- `public/app.js`
- `public/modules/spaces/shared-voice-room.js`
- shared-space room event storage in `server/static_server.py`
- shared voice tests in `tests/shared_voice_room.test.mjs`

Findings before the recovery changes:

- Local microphone access is currently requested in `startSharedVoice()` through
  `navigator.mediaDevices.getUserMedia(...)`. The old `maybeAutoJoinSharedVoice`
  path is no longer present, and `handleSharedVoiceSignal()` does not call
  `getUserMedia()`.
- Peer connections are created by `ensureSharedVoicePeer()` after the local
  voice state is active and a local stream exists. That path can be reached from
  current voice memberships in `syncSharedVoiceRoomPeers()` or from incoming
  offers found in retained room events.
- Local leave/cleanup is triggered by the local voice toggle through
  `stopSharedVoice()`, which publishes peer `hangup` events and a room `leave`
  event before `resetSharedVoiceRuntime()`. Remote `leave`/`hangup` events close
  a peer through `closeSharedVoicePeer(...)`; production still depends on the
  broader shared-space room processing loop to decide when peers disappear.
- Production room presence is account/device scoped. The device id comes from
  the signed-in user plus `wasmAgent.clientDevice.v1` in browser local storage,
  so duplicate tabs in the same browser profile can share one device identity.
  It is not tab-scoped.
- Room history is retained. The helper layer has epoch, freshness, leave, and
  local-baseline checks, but a refreshed client still re-reads retained events.
  Any future production port must keep target epoch and local join-baseline
  checks on every offer, answer, ICE, mute, hangup, and leave event.

Recovery change now staged in production while the feature remains default-off:

- Production voice now uses a page-scoped voice `from_device_id` plus
  `from_client_id` for voice membership, while carrying the account/browser
  device separately as `from_account_device_id`.
- Production peer discovery now reads current voice memberships from `join` and
  `membership` events rather than treating shared-space presence as voice
  consent.
- Production sends a best-effort local `leave` event on `pagehide`.
- The production controls remain hidden unless
  `HERMES_WASM_AGENT_SHARED_VOICE_ENABLED=1` is set, so `/voice-lab` is still
  the primary proof surface before real rollout.
- Production now emits the same structured lifecycle logs as the lab with
  `console.debug("[wasm-agent shared-voice]", record)`.

## Debug Log Format

Every voice lifecycle log line is a structured object emitted with
`console.debug("[wasm-agent voice-lab]", record)` in the lab and
`console.debug("[wasm-agent shared-voice]", record)` in the staged production
path:

```json
{
  "scope": "wasm-agent.voice-lab",
  "at": "2026-05-10T00:00:00.000Z",
  "roomId": "voice-lab",
  "localDeviceId": "vl-dev-...",
  "localClientId": "vl-client-...",
  "localMembershipState": "idle|joining|joined|leaving|reconnecting",
  "localJoinEpoch": "voice_lab_join_...",
  "eventType": "offer-received",
  "fromDeviceId": "vl-dev-peer",
  "toDeviceId": "vl-dev-local",
  "peerDeviceId": "vl-dev-peer",
  "callId": "voice_lab_...",
  "accepted": true,
  "ignored": false,
  "ignoreReason": ""
}
```

Required lifecycle events in the lab:

- `local-join-click`
- `getUserMedia`
- `join-event-publish`
- `membership-event-publish`
- `local-leave-click`
- `leave-event-publish`
- `remote-participant-joined`
- `remote-participant-left`
- `offer-received`
- `answer-received`
- `ice-received`
- `peer-connection-created`
- `peer-connection-closed`
- `stale-event-ignored`
- `event-ignored-local-not-joined`
- `event-ignored-target-mismatch`
- `event-ignored-epoch-mismatch`

Hard invariant:

- Remote events never call `getUserMedia()`.
- Remote events never call the local leave path.

## Isolated Voice Lab

Route:

- `/voice-lab`

Backend endpoint:

- `/voice-lab/room`

The lab page contains only:

- room id input
- local device/client id display
- Join Voice button
- Leave Voice button
- participant list
- event log panel
- local state panel
- remote audio elements

Lifecycle:

```text
idle -> joining -> joined -> leaving -> idle
```

Rules enforced by the lab:

- Only `joinVoice()` calls `navigator.mediaDevices.getUserMedia(...)`.
- `joinVoice()` only runs after a local Join Voice click.
- Each page gets a page-scoped `localClientId` and a derived
  `localDeviceId`, so duplicate tabs do not overwrite each other.
- Each join creates a new `joinEpoch`.
- Each signal carries `room_id`, `from_device_id`, `from_client_id`,
  `to_device_id`, `join_epoch`, `target_join_epoch`, and `call_id`.
- Incoming offer, answer, ICE, and mute events are ignored unless local state is
  `joined`.
- Incoming offer, answer, ICE, and mute events are ignored unless they target
  this tab's current local device and join epoch.
- Retained events before the local join baseline are ignored.
- Remote leave closes only that remote peer.
- Local leave stops only local tracks and local peer connections, then publishes
  this participant's leave.
- Empty-room cleanup is not a room command; stale participants age out by
  membership heartbeat TTL and presence TTL.

## Required Manual Matrix

Run with two browser clients, for example normal tab plus incognito, signed into
the same local wasm-agent account if auth is enabled. The automated browser
smoke test uses two same-profile tabs in headless Chromium with fake media
devices; real microphone prompt and human audio confirmation still require the
manual run.

| # | Check | Status |
|---|---|---|
| 1 | A opens lab, B opens lab: no microphone prompt yet. | Automated pass: no `getUserMedia` log before Join |
| 2 | A clicks Join: only A gets microphone prompt. | Automated pass: only A gets local stream; real prompt is manual |
| 3 | B does not auto-join. | Automated pass |
| 4 | B clicks Join: B gets microphone prompt. | Automated pass: B gets local stream after local click; real prompt is manual |
| 5 | A and B can hear each other. | Automated pass: both receive remote audio tracks; human listening is manual |
| 6 | A leaves: B remains joined. | Automated pass |
| 7 | A rejoins: A and B reconnect. | Automated pass |
| 8 | B leaves: A remains joined. | Automated pass |
| 9 | B rejoins: A and B reconnect. | Automated pass |
| 10 | A refreshes while B stays: B remains joined. | Automated pass |
| 11 | A rejoins after refresh: voice reconnects. | Automated pass |
| 12 | B refreshes while A stays: A remains joined. | Automated pass |
| 13 | Duplicate tabs from same account do not hijack each other. | Automated pass plus backend test |
| 14 | Old retained offers/answers/ICE are ignored after rejoin. | Automated pass plus helper/static tests |
| 15 | Closing one tab cleans up only that tab's participant. | Automated pass |
| 16 | Three clients can join as a small mesh; one can leave/rejoin/refresh without disrupting the other two. | Automated pass with fake media |

Automated verifier:

```bash
python3 tests/voice_lab_browser_smoke.py
```

## Production Port Gate

Do not enable production shared-space voice by default or treat the production
path as rollout-ready until the full manual matrix passes with real browsers and
real audio.

Production now follows the lab's critical identity split: voice membership uses
a page-scoped voice participant id and carries account/browser device identity
separately. The remaining rollout gate is real two-client production testing
with `HERMES_WASM_AGENT_SHARED_VOICE_ENABLED=1`, then a three-client smoke on
real devices. The implementation is a browser mesh: three people creates three
peer connections, four people creates six, and larger rooms should wait for an
SFU/media-server design rather than stretching this path.

## Rollback

Production shared-space voice is disabled by default through
`features.sharedVoice.enabled: false`. Keep it that way unless a deliberate
test sets `HERMES_WASM_AGENT_SHARED_VOICE_ENABLED=1`. If a later production
port is unstable, remove that env var or set it to `0`; as a belt-and-suspenders
rollback, hide the production `sharedVoiceBar`. Leave `/voice-lab` available as
the isolated diagnostic path so signaling and membership behavior can continue
to be tested without pulling the full shared-space UI back into the failure
loop.
