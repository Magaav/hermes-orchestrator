import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../public/voice-lab.js", import.meta.url), "utf8");
const html = await readFile(new URL("../public/voice-lab.html", import.meta.url), "utf8");
const server = await readFile(new URL("../server/static_server.py", import.meta.url), "utf8");

assert(html.includes('id="roomInput"'), "voice lab needs a room id input");
assert(html.includes('id="joinButton"'), "voice lab needs a Join Voice button");
assert(html.includes('id="leaveButton"'), "voice lab needs a Leave Voice button");
assert(html.includes('id="participantList"'), "voice lab needs a participant list");
assert(html.includes('id="eventLog"'), "voice lab needs an event log panel");
assert(html.includes('id="statePanel"'), "voice lab needs a local state panel");
assert(html.includes('id="remoteAudioList"'), "voice lab needs remote audio elements");

assert(server.includes('if path.split("?", 1)[0] == "/voice-lab"'), "server must route /voice-lab to the isolated lab page");
assert(server.includes('if path == "/voice-lab/room"'), "voice lab room endpoint is missing");
assert(server.includes("request_voice_lab_client_id"), "voice lab must carry a page-scoped client id");
assert(server.includes("request_voice_lab_device_id"), "voice lab must carry a lab-local device id");
assert(server.includes('"from_device_id": request_voice_lab_device_id(user, handler)'), "server must override spoofed voice-lab sender device ids");

const joinStart = source.indexOf("async function joinVoice");
const leaveStart = source.indexOf("async function leaveVoice");
const signalStart = source.indexOf("async function handleSignalEvent");
const signalEnd = source.indexOf("function peerLabel");
assert(joinStart > -1 && leaveStart > joinStart, "joinVoice/leaveVoice functions were not found");
assert(signalStart > -1 && signalEnd > signalStart, "handleSignalEvent boundaries were not found");
const joinBody = source.slice(joinStart, leaveStart);
const signalBody = source.slice(signalStart, signalEnd);
assert(joinBody.includes("navigator.mediaDevices.getUserMedia"), "only the local join path may request microphone media");
assert(!signalBody.includes("getUserMedia"), "remote signal handling must never request microphone media");
assert(!signalBody.includes("leaveVoice"), "remote signal handling must never call the local leave path");
assert(signalBody.includes("event-ignored-local-not-joined"), "signals must be ignored when the local client is not joined");
assert(signalBody.includes("event-ignored-target-mismatch"), "signals for other devices must be ignored");
assert(signalBody.includes("event-ignored-epoch-mismatch"), "signals for older/different epochs must be ignored");
assert(signalBody.includes("remote-participant-left"), "remote leave must be handled as a peer-only transition");

for (const field of [
  "roomId",
  "localDeviceId",
  "localClientId",
  "localMembershipState",
  "localJoinEpoch",
  "eventType",
  "fromDeviceId",
  "toDeviceId",
  "peerDeviceId",
  "accepted",
  "ignored",
  "ignoreReason",
]) {
  assert(source.includes(field), `voice lab logs must include ${field}`);
}

console.log("voice lab static checks ok");
