import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { Buffer } from "node:buffer";

const source = await readFile(new URL("../public/modules/spaces/shared-voice-room.js", import.meta.url), "utf8");
const room = await import(`data:text/javascript;base64,${Buffer.from(source).toString("base64")}`);

const baseMs = Date.parse("2026-05-10T20:00:00.000Z");
const schema = "hermes.wasm_agent.shared_space.voice_signal.v1";

function voiceEvent(id, type, from, to = "", callId = "voice-a", offsetMs = 0, extra = {}) {
  return {
    id,
    kind: "voice-signal",
    created_at: new Date(baseMs + offsetMs).toISOString(),
    payload: {
      voice_schema: schema,
      call_id: callId,
      type,
      from_device_id: from,
      to_device_id: to,
      ...extra,
    },
  };
}

{
  const joined = room.sharedVoiceJoinedDeviceIdSet([
    voiceEvent("a-join", "join", "alpha"),
    voiceEvent("b-join", "join", "beta"),
    voiceEvent("a-hangup", "hangup", "alpha", "beta", "voice-ab", 1000),
  ], { nowMs: baseMs + 2000 });
  assert.deepEqual([...joined].sort(), ["beta"], "hangup should retire only the leaving device");
}

{
  const offers = room.sharedVoiceIncomingOfferEvents([
    voiceEvent("offer-old", "offer", "alpha", "beta", "voice-old", 0, { sdp: "old" }),
    voiceEvent("leave-alpha", "leave", "alpha", "", "voice-old", 1000),
  ], "beta", { nowMs: baseMs + 2000 });
  assert.equal(offers.length, 0, "offers older than a leave must not re-open the room");
}

{
  const offers = room.sharedVoiceIncomingOfferEvents([
    voiceEvent("offer-old", "offer", "alpha", "beta", "voice-old", 0, { sdp: "old" }),
    voiceEvent("leave-alpha", "leave", "alpha", "", "voice-old", 1000),
    voiceEvent("join-alpha", "join", "alpha", "", "voice-room", 2000),
  ], "beta", { nowMs: baseMs + 3000 });
  assert.equal(offers.length, 0, "rejoining without a new offer must not revive an old offer");
}

{
  const offers = room.sharedVoiceIncomingOfferEvents([
    voiceEvent("offer-old", "offer", "alpha", "beta", "voice-old", 0, { sdp: "old" }),
    voiceEvent("leave-alpha", "leave", "alpha", "", "voice-old", 1000),
    voiceEvent("join-alpha", "join", "alpha", "", "voice-room", 2000),
    voiceEvent("offer-new", "offer", "alpha", "beta", "voice-new", 3000, { sdp: "new" }),
  ], "beta", { nowMs: baseMs + 4000 });
  assert.equal(offers.length, 1);
  assert.equal(offers[0].payload.call_id, "voice-new");
  assert.equal(offers[0].payload.sdp, "new");
}

{
  const events = [
    voiceEvent("offer-old", "offer", "alpha", "beta", "voice-old", 0, { sdp: "old" }),
    voiceEvent("beta-leave", "leave", "beta", "alpha", "voice-old", 1000),
    voiceEvent("beta-join", "join", "beta", "", "voice-room", 2000),
    voiceEvent("offer-new", "offer", "alpha", "beta", "voice-new", 3000, { sdp: "new" }),
  ];
  const join = room.sharedVoiceLatestJoinEvent(events, "beta", { nowMs: baseMs + 4000 });
  assert.equal(join.event.id, "beta-join");
  assert.equal(room.sharedVoiceEventPrecedesBaseline(events[0], room.sharedVoiceEventCreatedMs(join.event), join.event.id), true);
  assert.equal(room.sharedVoiceEventPrecedesBaseline(events[3], room.sharedVoiceEventCreatedMs(join.event), join.event.id), false);
}

{
  const offers = room.sharedVoiceIncomingOfferEvents([
    voiceEvent("offer-old", "offer", "alpha", "beta", "voice-old", 0, { sdp: "old" }),
    voiceEvent("hangup-beta", "hangup", "beta", "alpha", "voice-old", 1000),
  ], "beta", { nowMs: baseMs + 2000 });
  assert.equal(offers.length, 0, "outgoing hangup should close older incoming offers from that peer");
}

{
  assert.equal(room.sharedVoiceShouldInitiateRoomOffer("b-device", "a-device"), true);
  assert.equal(room.sharedVoiceShouldInitiateRoomOffer("a-device", "b-device"), false);
  assert.equal(room.sharedVoiceShouldInitiateRoomOffer("", "b-device"), false);
}

{
  const joined = room.sharedVoiceJoinedDeviceIdSet([
    voiceEvent("fresh", "join", "fresh", "", "voice-room", 0),
    voiceEvent("stale", "join", "stale", "", "voice-room", -180000),
  ], { nowMs: baseMs + 1000, staleMs: 120000 });
  assert.deepEqual([...joined], ["fresh"], "stale voice events must age out of room state");
}

console.log("shared voice room logic ok");
