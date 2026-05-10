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

function membershipDevices(events, offsetMs = 0) {
  return [...room.sharedVoiceMemberships(events, {
    nowMs: baseMs + offsetMs,
    membershipTtlMs: 12000,
  }).keys()].sort();
}

function signal(id, type, from, to, fromEpoch, targetEpoch, offsetMs = 0, extra = {}) {
  return voiceEvent(id, type, from, to, `${from}-${to}`, offsetMs, {
    join_epoch: fromEpoch,
    target_join_epoch: targetEpoch,
    room_id: "room-one",
    ...extra,
  });
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

{
  const events = [
    voiceEvent("a-join", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("a-heartbeat", "membership", "A", "", "room", 5000, { join_epoch: "A1", join_event_id: "a-join" }),
  ];
  assert.deepEqual(membershipDevices(events, 6000), ["A"], "1. A joins as local membership");
  assert.deepEqual(membershipDevices(events, 20000), [], "12. remote disconnect ages out only that membership");
}

{
  const events = [
    voiceEvent("a-join", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("a-heartbeat", "membership", "A", "", "room", 5000, { join_epoch: "A1", join_event_id: "a-join" }),
  ];
  assert.equal(room.sharedVoiceMemberships(events, { nowMs: baseMs + 6000, membershipTtlMs: 12000 }).has("B"), false, "1. B does not auto-join");
}

{
  const events = [
    voiceEvent("a-join", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
  ];
  assert.deepEqual(membershipDevices(events, 2000), ["A", "B"], "2. A and B are both joined after local joins");
  assert.equal(room.sharedVoiceShouldInitiateRoomOffer("B", "A"), true, "2. deterministic mesh caller exists");
}

{
  const events = [
    voiceEvent("a-join", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
    voiceEvent("a-leave", "leave", "A", "B", "room", 2000, { join_epoch: "A1", target_join_epoch: "B1" }),
  ];
  assert.deepEqual(membershipDevices(events, 3000), ["B"], "3. A leaves, B stays");
}

{
  const events = [
    voiceEvent("a-join", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
    voiceEvent("b-leave", "leave", "B", "A", "room", 2000, { join_epoch: "B1", target_join_epoch: "A1" }),
  ];
  assert.deepEqual(membershipDevices(events, 3000), ["A"], "4. B leaves, A stays");
}

{
  const events = [
    voiceEvent("a-join-old", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
    voiceEvent("b-heartbeat", "membership", "B", "", "room", 10000, { join_epoch: "B1", join_event_id: "b-join" }),
  ];
  assert.deepEqual(membershipDevices(events, 15000), ["B"], "5. A refresh/disconnect expires while B stays");
}

{
  const events = [
    voiceEvent("a-join-old", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
    voiceEvent("a-join-new", "join", "A", "", "room", 13000, { join_epoch: "A2" }),
    signal("b-offer-a2", "offer", "B", "A", "B1", "A2", 14000, { sdp: "new" }),
  ];
  const local = { deviceId: "A", joinEpoch: "A2" };
  assert.equal(room.sharedVoiceSignalTargetsLocalMembership(events[3].payload, local), true, "6. A rejoins with a new epoch and can reconnect");
}

{
  const events = [
    voiceEvent("a-join", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join-old", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
    voiceEvent("a-heartbeat", "membership", "A", "", "room", 10000, { join_epoch: "A1", join_event_id: "a-join" }),
  ];
  assert.deepEqual(membershipDevices(events, 15000), ["A"], "7. B refresh/disconnect expires while A stays");
}

{
  const events = [
    voiceEvent("a-join-old", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("b-join-old", "join", "B", "", "room", 1000, { join_epoch: "B1" }),
    voiceEvent("a-leave", "leave", "A", "B", "room", 2000, { join_epoch: "A1" }),
    voiceEvent("b-leave", "leave", "B", "A", "room", 3000, { join_epoch: "B1" }),
    voiceEvent("a-join-new", "join", "A", "", "room", 4000, { join_epoch: "A2" }),
    voiceEvent("b-join-new", "join", "B", "", "room", 5000, { join_epoch: "B2" }),
  ];
  assert.deepEqual(membershipDevices(events, 6000), ["A", "B"], "8. both leave and rejoin with new epochs");
}

{
  const events = [
    voiceEvent("tab-one", "join", "A-tab-1", "", "room", 0, { from_user_id: "same", join_epoch: "T1" }),
    voiceEvent("tab-two", "join", "A-tab-2", "", "room", 1000, { from_user_id: "same", join_epoch: "T2" }),
  ];
  assert.deepEqual(membershipDevices(events, 2000), ["A-tab-1", "A-tab-2"], "9. duplicate tabs keep separate device memberships");
}

{
  const events = [
    voiceEvent("phone", "join", "phone-device", "", "room", 0, { from_user_id: "same", join_epoch: "P1" }),
  ];
  assert.deepEqual(membershipDevices(events, 1000), ["phone-device"], "10. one same-account device joined");
  assert.equal(room.sharedVoiceMemberships(events, { nowMs: baseMs + 1000, membershipTtlMs: 12000 }).has("laptop-device"), false, "10. second same-account device still needs local consent");
}

{
  const local = { deviceId: "A", joinEpoch: "A2" };
  const oldOffer = signal("old-offer", "offer", "B", "A", "B1", "A1", 0, { sdp: "old" });
  const oldIce = signal("old-ice", "ice-candidate", "B", "A", "B1", "A1", 1, { candidate: "{}" });
  assert.equal(room.sharedVoiceSignalTargetsLocalMembership(oldOffer.payload, local), false, "11. old offers before rejoin are ignored");
  assert.equal(room.sharedVoiceSignalTargetsLocalMembership(oldIce.payload, local), false, "11. old candidates before rejoin are ignored");
}

{
  const events = [
    voiceEvent("a-join-1", "join", "A", "", "room", 0, { join_epoch: "A1" }),
    voiceEvent("a-leave-1", "leave", "A", "", "room", 100, { join_epoch: "A1" }),
    voiceEvent("a-join-2", "join", "A", "", "room", 200, { join_epoch: "A2" }),
    voiceEvent("a-leave-2", "leave", "A", "", "room", 300, { join_epoch: "A2" }),
    voiceEvent("a-join-3", "join", "A", "", "room", 400, { join_epoch: "A3" }),
  ];
  const membership = room.sharedVoiceMemberships(events, { nowMs: baseMs + 1000, membershipTtlMs: 12000 }).get("A");
  assert.equal(membership.joinEpoch, "A3", "13. rapid join/leave/rejoin keeps latest epoch");
}

{
  const remoteLeave = signal("remote-leave", "leave", "B", "A", "B1", "A1");
  assert.equal(room.sharedVoiceSignalTargetsLocalMembership(remoteLeave.payload, { deviceId: "A", joinEpoch: "A2" }), false, "14. remote leave cannot target a newer local membership");
}

console.log("shared voice room logic ok");
