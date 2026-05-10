const DEFAULT_SIGNAL_KIND = "voice-signal";
const DEFAULT_SIGNAL_SCHEMA = "hermes.wasm_agent.shared_space.voice_signal.v1";
const DEFAULT_STALE_MS = 2 * 60 * 1000;

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
  const joined = new Set();
  const left = new Set();
  for (const { payload } of sharedVoiceSignalEvents(events, options).reverse()) {
    const deviceId = String(payload.from_device_id || "").trim();
    if (!deviceId || joined.has(deviceId)) continue;
    if (payload.type === "leave" || payload.type === "hangup") {
      left.add(deviceId);
      continue;
    }
    if (payload.type === "join" && !left.has(deviceId)) joined.add(deviceId);
  }
  return joined;
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
