const DEFAULT_SIGNAL_KIND = "voice-signal";
const DEFAULT_SIGNAL_SCHEMA = "hermes.wasm_agent.shared_space.voice_signal.v1";
const DEFAULT_STALE_MS = 2 * 60 * 1000;

export function sharedVoiceNewJoinEpoch(prefix = "voice_join") {
  const stamp = Date.now().toString(36);
  const random = Math.random().toString(36).slice(2, 10);
  return `${prefix}_${stamp}_${random}`;
}

export function sharedVoiceSignalPayload(event, schema = DEFAULT_SIGNAL_SCHEMA) {
  const payload = event?.payload;
  if (!payload || typeof payload !== "object") return null;
  if (payload.voice_schema !== schema) return null;
  return payload;
}

export function sharedVoiceSignalIsFresh(event, nowMs = Date.now(), staleMs = DEFAULT_STALE_MS) {
  const created = Date.parse(event?.created_at || "");
  if (!Number.isFinite(created)) return true;
  return nowMs - created <= staleMs;
}

export function sharedVoiceEventCreatedMs(event) {
  const created = Date.parse(event?.created_at || "");
  return Number.isFinite(created) ? created : 0;
}

export function sharedVoiceShouldInitiateRoomOffer(currentDeviceId, peerDeviceId) {
  if (!currentDeviceId || !peerDeviceId) return false;
  return String(currentDeviceId) > String(peerDeviceId);
}

function sharedVoiceSignalEvents(events, options = {}) {
  const kind = options.kind || DEFAULT_SIGNAL_KIND;
  const schema = options.schema || DEFAULT_SIGNAL_SCHEMA;
  const nowMs = Number.isFinite(options.nowMs) ? options.nowMs : Date.now();
  const staleMs = Number.isFinite(options.staleMs) ? options.staleMs : DEFAULT_STALE_MS;
  return (Array.isArray(events) ? events : [])
    .filter((event) => event?.kind === kind && sharedVoiceSignalIsFresh(event, nowMs, staleMs))
    .map((event) => ({ event, payload: sharedVoiceSignalPayload(event, schema) }))
    .filter((item) => item.payload);
}

export function sharedVoiceJoinedDeviceIdSet(events, options = {}) {
  return new Set(sharedVoiceMemberships(events, options).keys());
}

export function sharedVoiceMemberships(events, options = {}) {
  const memberships = new Map();
  const closed = new Map();
  const nowMs = Number.isFinite(options.nowMs) ? options.nowMs : Date.now();
  const membershipTtlMs = Number.isFinite(options.membershipTtlMs) ? options.membershipTtlMs : 0;
  for (const { event, payload } of sharedVoiceSignalEvents(events, options).reverse()) {
    const deviceId = String(payload.from_device_id || "").trim();
    if (!deviceId || memberships.has(deviceId)) continue;
    const membershipEpoch = String(payload.join_epoch || payload.join_event_id || payload.call_id || "").trim();
    const closeEpoch = String(payload.join_epoch || payload.join_event_id || "").trim();
    const closedEpochs = closed.get(deviceId) || new Set();
    if (payload.type === "leave" || payload.type === "hangup") {
      if (closeEpoch) closedEpochs.add(closeEpoch);
      else closedEpochs.add("*");
      closed.set(deviceId, closedEpochs);
      continue;
    }
    if (payload.type === "join" || payload.type === "membership") {
      if (closedEpochs.has("*") || (membershipEpoch && closedEpochs.has(membershipEpoch))) continue;
      const joinedAtMs = sharedVoiceEventCreatedMs(event);
      if (membershipTtlMs && joinedAtMs && nowMs - joinedAtMs > membershipTtlMs) continue;
      memberships.set(deviceId, {
        deviceId,
        userId: String(payload.from_user_id || "").trim(),
        joinEpoch: String(payload.join_epoch || "").trim(),
        joinEventId: String(payload.join_event_id || event?.id || "").trim(),
        joinedAtMs,
        event,
        payload,
      });
    }
  }
  return memberships;
}

export function sharedVoiceLatestJoinEvent(events, currentDeviceId, options = {}) {
  const deviceId = String(currentDeviceId || "").trim();
  if (!deviceId) return null;
  for (const item of sharedVoiceSignalEvents(events, options).reverse()) {
    if (item.payload.type === "join" && String(item.payload.from_device_id || "").trim() === deviceId) {
      return item;
    }
  }
  return null;
}

export function sharedVoiceEventPrecedesBaseline(event, baselineMs = 0, baselineId = "") {
  const createdMs = sharedVoiceEventCreatedMs(event);
  if (!baselineMs || !createdMs) return false;
  if (createdMs < baselineMs) return true;
  return Boolean(baselineId && createdMs === baselineMs && String(event?.id || "") < String(baselineId));
}

export function sharedVoiceSignalTargetsLocalMembership(payload, local = {}) {
  if (!payload || typeof payload !== "object") return false;
  const localDeviceId = String(local.deviceId || "").trim();
  if (!localDeviceId || String(payload.to_device_id || "").trim() !== localDeviceId) return false;
  const targetEpoch = String(payload.target_join_epoch || payload.to_join_epoch || "").trim();
  const targetJoinEventId = String(payload.target_join_event_id || payload.to_join_event_id || "").trim();
  const localEpoch = String(local.joinEpoch || "").trim();
  const localJoinEventId = String(local.joinEventId || "").trim();
  if (targetEpoch || targetJoinEventId) {
    return Boolean(
      (targetEpoch && localEpoch && targetEpoch === localEpoch)
      || (targetJoinEventId && localJoinEventId && targetJoinEventId === localJoinEventId)
    );
  }
  return !localEpoch && !localJoinEventId;
}

export function sharedVoiceSignalMatchesRemoteMembership(payload, remote = {}) {
  if (!payload || typeof payload !== "object") return false;
  const remoteDeviceId = String(remote.deviceId || "").trim();
  if (!remoteDeviceId || String(payload.from_device_id || "").trim() !== remoteDeviceId) return false;
  const epoch = String(payload.join_epoch || "").trim();
  const joinEventId = String(payload.join_event_id || "").trim();
  const remoteEpoch = String(remote.joinEpoch || "").trim();
  const remoteJoinEventId = String(remote.joinEventId || "").trim();
  if (epoch || joinEventId) {
    return Boolean(
      (epoch && remoteEpoch && epoch === remoteEpoch)
      || (joinEventId && remoteJoinEventId && joinEventId === remoteJoinEventId)
    );
  }
  return !remoteEpoch && !remoteJoinEventId;
}

export function sharedVoiceIncomingOfferEvents(events, currentDeviceId, options = {}) {
  const deviceId = String(currentDeviceId || "").trim();
  if (!deviceId) return [];
  const closedCallIds = new Set();
  const closedDeviceIds = new Set();
  const latestByPeer = new Map();
  for (const { event, payload } of sharedVoiceSignalEvents(events, options).reverse()) {
    const fromDeviceId = String(payload.from_device_id || "").trim();
    const toDeviceId = String(payload.to_device_id || "").trim();
    if (payload.type === "leave" && fromDeviceId) {
      closedDeviceIds.add(fromDeviceId);
      continue;
    }
    if (payload.type === "hangup" && (toDeviceId === deviceId || fromDeviceId === deviceId)) {
      if (payload.call_id) closedCallIds.add(payload.call_id);
      const otherDeviceId = fromDeviceId === deviceId ? toDeviceId : fromDeviceId;
      if (otherDeviceId) closedDeviceIds.add(otherDeviceId);
      continue;
    }
    if (payload.type !== "offer" || closedCallIds.has(payload.call_id)) continue;
    if (closedDeviceIds.has(fromDeviceId)) continue;
    if (toDeviceId !== deviceId || fromDeviceId === deviceId) continue;
    if (!latestByPeer.has(fromDeviceId)) latestByPeer.set(fromDeviceId, { event, payload });
  }
  return Array.from(latestByPeer.values()).reverse();
}

export function latestIncomingSharedVoiceOfferEvent(events, currentDeviceId, options = {}) {
  return sharedVoiceIncomingOfferEvents(events, currentDeviceId, options)[0] || null;
}
