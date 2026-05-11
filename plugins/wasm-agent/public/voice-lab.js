import {
  sharedVoiceEventCreatedMs,
  sharedVoiceEventPrecedesBaseline,
  sharedVoiceLatestJoinEvent,
  sharedVoiceMemberships,
  sharedVoiceNewJoinEpoch,
  sharedVoiceSignalIsFresh,
  sharedVoiceSignalMatchesRemoteMembership,
  sharedVoiceSignalPayload,
  sharedVoiceSignalTargetsLocalMembership,
  sharedVoiceShouldInitiateRoomOffer,
} from "/modules/spaces/shared-voice-room.js";

const SIGNAL_KIND = "voice-signal";
const SIGNAL_SCHEMA = "hermes.wasm_agent.shared_space.voice_signal.v1";
const STALE_MS = 2 * 60 * 1000;
const MEMBERSHIP_STALE_MS = 12000;
const MEMBERSHIP_HEARTBEAT_MS = 5000;
const POLL_MS = 900;
const DEFAULT_ICE_SERVERS = [{ urls: "stun:stun.l.google.com:19302" }];
const CLIENT_DEVICE_STORAGE_KEY = "wasmAgent.clientDevice.v1";
const VOICE_LAB_ROOM_STORAGE_KEY = "wasmAgent.voiceLab.room.v1";
const LOG_LIMIT = 180;

const els = {
  authState: document.querySelector("#authState"),
  roomInput: document.querySelector("#roomInput"),
  localDeviceId: document.querySelector("#localDeviceId"),
  localClientId: document.querySelector("#localClientId"),
  joinButton: document.querySelector("#joinButton"),
  leaveButton: document.querySelector("#leaveButton"),
  participantList: document.querySelector("#participantList"),
  statePanel: document.querySelector("#statePanel"),
  eventLog: document.querySelector("#eventLog"),
  remoteAudioList: document.querySelector("#remoteAudioList"),
};

const state = {
  auth: null,
  config: null,
  room: null,
  roomId: "",
  status: "idle",
  localClientId: pageScopedId(),
  localDeviceId: "",
  localStream: null,
  joinEpoch: "",
  joinEventId: "",
  joinedAtMs: 0,
  pollTimer: 0,
  pollBusy: false,
  lastHeartbeatAt: 0,
  peers: new Map(),
  processedEventIds: new Set(),
  logs: [],
  processing: Promise.resolve(),
};

state.localDeviceId = `vl-dev-${state.localClientId}`;

function randomId(prefix) {
  const cryptoId = window.crypto?.randomUUID?.().replace(/-/g, "").slice(0, 18);
  const fallback = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  return `${prefix}-${cryptoId || fallback}`.toLowerCase();
}

function pageScopedId() {
  return randomId("vl-client");
}

function clientDeviceId() {
  try {
    const raw = JSON.parse(localStorage.getItem(CLIENT_DEVICE_STORAGE_KEY) || "{}");
    if (raw?.id && /^[a-z0-9_-]{8,96}$/i.test(raw.id)) return raw.id;
  } catch {
    // The voice lab carries its own tab-scoped participant id.
  }
  const id = randomId("dev");
  try {
    localStorage.setItem(CLIENT_DEVICE_STORAGE_KEY, JSON.stringify({ id, created_at: new Date().toISOString() }));
  } catch {
    // The backend can still authenticate the request from the session cookie.
  }
  return id;
}

function cleanRoomId(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 72) || "voice-lab";
}

function currentRoomId() {
  return cleanRoomId(els.roomInput?.value || state.roomId || "voice-lab");
}

function signalPayload(event) {
  return sharedVoiceSignalPayload(event, SIGNAL_SCHEMA);
}

function voiceMemberships(room = state.room) {
  return sharedVoiceMemberships(room?.events, {
    kind: SIGNAL_KIND,
    schema: SIGNAL_SCHEMA,
    staleMs: STALE_MS,
    membershipTtlMs: MEMBERSHIP_STALE_MS,
  });
}

function localMembership() {
  return {
    roomId: state.roomId,
    deviceId: state.localDeviceId,
    joinEpoch: state.joinEpoch,
    joinEventId: state.joinEventId,
    joinedAtMs: state.joinedAtMs,
  };
}

function eventBeforeCurrentJoin(event, payload) {
  if (!payload || payload.type === "join") return false;
  return sharedVoiceEventPrecedesBaseline(event, Number(state.joinedAtMs || 0), state.joinEventId || "");
}

function summarizeError(error) {
  return String(error?.message || error || "unknown error").slice(0, 180);
}

function logVoice(eventType, details = {}) {
  const payload = details.payload || {};
  const record = {
    scope: "wasm-agent.voice-lab",
    at: new Date().toISOString(),
    roomId: String(details.roomId || payload.room_id || state.roomId || currentRoomId() || ""),
    localDeviceId: String(state.localDeviceId || ""),
    localClientId: String(state.localClientId || ""),
    localMembershipState: String(state.status || "idle"),
    localJoinEpoch: String(state.joinEpoch || ""),
    eventType,
    fromDeviceId: String(details.fromDeviceId || payload.from_device_id || ""),
    toDeviceId: String(details.toDeviceId || payload.to_device_id || ""),
    peerDeviceId: String(details.peerDeviceId || ""),
    callId: String(details.callId || payload.call_id || ""),
    accepted: Boolean(details.accepted),
    ignored: Boolean(details.ignored || details.accepted === false),
    ignoreReason: String(details.ignoreReason || ""),
  };
  state.logs.push(record);
  if (state.logs.length > LOG_LIMIT) state.logs.splice(0, state.logs.length - LOG_LIMIT);
  console.debug("[wasm-agent voice-lab]", record);
  render();
  return record;
}

async function fetchJson(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), Number(options.timeoutMs || 12000));
  try {
    const response = await fetch(path, {
      method: options.method || "GET",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "X-Wasm-Agent-Device-Id": clientDeviceId(),
        "X-Wasm-Agent-Voice-Lab-Client-Id": state.localClientId,
        "X-Wasm-Agent-Voice-Lab-Device-Id": state.localDeviceId,
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
      keepalive: Boolean(options.keepalive),
    });
    const text = await response.text();
    let payload = {};
    try {
      payload = text ? JSON.parse(text) : {};
    } catch {
      payload = { ok: false, error: { message: text.slice(0, 600) } };
    }
    if (!response.ok || payload.ok === false) {
      const error = new Error(payload?.error?.message || `HTTP ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }
    return payload;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function loadSession() {
  try {
    const payload = await fetchJson("/auth/session", { timeoutMs: 5000 });
    state.auth = payload;
  } catch (error) {
    state.auth = { authenticated: false, error: summarizeError(error) };
  }
}

async function loadConfig() {
  try {
    const payload = await fetchJson("/config.json", { timeoutMs: 5000 });
    state.config = payload;
  } catch {
    state.config = {};
  }
}

function iceServers() {
  const configured = state.config?.features?.sharedVoice?.iceServers;
  return Array.isArray(configured) && configured.length ? configured : DEFAULT_ICE_SERVERS;
}

async function postRoom(action, details = {}) {
  const roomId = currentRoomId();
  state.roomId = roomId;
  try {
    localStorage.setItem(VOICE_LAB_ROOM_STORAGE_KEY, roomId);
  } catch {
    // Last-room persistence is convenience only.
  }
  const payload = await fetchJson("/voice-lab/room", {
    method: "POST",
    timeoutMs: details.timeoutMs || 12000,
    keepalive: details.keepalive,
    body: {
      action,
      room_id: roomId,
      ...details.body,
    },
  });
  if (payload.room) {
    state.room = payload.room;
    state.localDeviceId = payload.room.current_device_id || state.localDeviceId;
  }
  return payload.room || null;
}

function signalBody(type, details = {}) {
  return {
    kind: SIGNAL_KIND,
    payload: {
      voice_schema: SIGNAL_SCHEMA,
      type,
      room_id: state.roomId,
      call_id: details.call_id || `voice_lab_room_${state.roomId}`,
      from_device_id: state.localDeviceId,
      from_client_id: state.localClientId,
      to_device_id: details.to_device_id || "",
      join_epoch: Object.prototype.hasOwnProperty.call(details, "join_epoch") ? details.join_epoch : state.joinEpoch,
      join_event_id: Object.prototype.hasOwnProperty.call(details, "join_event_id") ? details.join_event_id : state.joinEventId,
      target_join_epoch: details.target_join_epoch || "",
      target_join_event_id: details.target_join_event_id || "",
      ...details,
    },
  };
}

async function sendSignal(type, details = {}) {
  const room = await postRoom("signal", {
    timeoutMs: details.timeoutMs,
    body: signalBody(type, details),
  });
  const payload = signalBody(type, details).payload;
  const eventType = type === "join"
    ? "join-event-publish"
    : type === "leave"
      ? "leave-event-publish"
      : `${type}-event-publish`;
  logVoice(eventType, {
    payload,
    accepted: true,
    peerDeviceId: details.to_device_id || "",
    callId: details.call_id || payload.call_id,
  });
  if (type === "join") markJoinBaseline(room);
  return room;
}

function sendSignalKeepalive(type, details = {}) {
  const roomId = currentRoomId();
  const body = {
    action: "signal",
    room_id: roomId,
    ...signalBody(type, details),
  };
  try {
    fetch("/voice-lab/room", {
      method: "POST",
      cache: "no-store",
      keepalive: true,
      headers: {
        "Content-Type": "application/json",
        "X-Wasm-Agent-Device-Id": clientDeviceId(),
        "X-Wasm-Agent-Voice-Lab-Client-Id": state.localClientId,
        "X-Wasm-Agent-Voice-Lab-Device-Id": state.localDeviceId,
      },
      body: JSON.stringify(body),
    }).catch(() => {});
  } catch {
    // Page unload leave is best-effort; membership TTL is the fallback.
  }
}

function markJoinBaseline(room = state.room) {
  const item = sharedVoiceLatestJoinEvent(room?.events, state.localDeviceId, {
    kind: SIGNAL_KIND,
    schema: SIGNAL_SCHEMA,
    staleMs: STALE_MS,
  });
  if (!item?.event) return;
  if (item.payload?.join_epoch && item.payload.join_epoch !== state.joinEpoch) return;
  state.joinedAtMs = sharedVoiceEventCreatedMs(item.event) || Date.now();
  state.joinEventId = item.event.id || "";
}

async function joinVoice() {
  if (state.status !== "idle") return;
  if (!state.auth?.authenticated) {
    logVoice("local-join-click", {
      accepted: false,
      ignored: true,
      fromDeviceId: state.localDeviceId,
      ignoreReason: "auth-required",
    });
    return;
  }
  state.roomId = currentRoomId();
  state.joinEpoch = sharedVoiceNewJoinEpoch("voice_lab_join");
  state.joinEventId = "";
  state.joinedAtMs = Date.now();
  state.lastHeartbeatAt = 0;
  state.processedEventIds = new Set();
  setStatus("joining");
  logVoice("local-join-click", { accepted: true, fromDeviceId: state.localDeviceId });
  try {
    const mediaProblem = mediaUnavailableReason();
    if (mediaProblem) throw new Error(mediaProblem);
    logVoice("getUserMedia", {
      accepted: true,
      fromDeviceId: state.localDeviceId,
      ignoreReason: "",
    });
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
      video: false,
    });
    state.localStream = stream;
    setStatus("joined");
    const joinedRoom = await sendSignal("join", {
      joined: true,
      call_id: `voice_lab_room_${state.roomId}`,
      join_epoch: state.joinEpoch,
      join_event_id: "",
    });
    await sendMembershipHeartbeat(true);
    startPolling();
    await processRoom(joinedRoom || state.room);
  } catch (error) {
    logVoice("getUserMedia", {
      accepted: false,
      ignored: true,
      fromDeviceId: state.localDeviceId,
      ignoreReason: summarizeError(error),
    });
    await cleanupLocalVoice({ publish: false, reason: "join-failed" });
  }
}

function mediaUnavailableReason() {
  if (!window.isSecureContext) return "HTTPS or localhost is required for microphone access.";
  if (!window.RTCPeerConnection) return "WebRTC is unavailable in this browser.";
  if (!navigator.mediaDevices?.getUserMedia) return "Microphone access is unavailable in this browser.";
  return "";
}

async function leaveVoice(reason = "local-leave") {
  if (!["joining", "joined", "reconnecting"].includes(state.status)) return;
  logVoice("local-leave-click", { accepted: true, fromDeviceId: state.localDeviceId });
  setStatus("leaving");
  try {
    if (state.joinEpoch) {
      await sendSignal("leave", {
        reason,
        call_id: `voice_lab_room_${state.roomId}`,
        join_epoch: state.joinEpoch,
        join_event_id: state.joinEventId,
      }).catch((error) => {
        logVoice("leave-event-publish", {
          accepted: false,
          ignored: true,
          fromDeviceId: state.localDeviceId,
          ignoreReason: summarizeError(error),
        });
      });
    }
  } finally {
    await cleanupLocalVoice({ publish: false, reason });
  }
}

async function cleanupLocalVoice({ publish = false, reason = "cleanup" } = {}) {
  if (publish && state.joinEpoch) {
    await sendSignal("leave", {
      reason,
      call_id: `voice_lab_room_${state.roomId}`,
      join_epoch: state.joinEpoch,
      join_event_id: state.joinEventId,
    }).catch(() => {});
  }
  stopPolling();
  closeAllPeers(reason);
  state.localStream?.getTracks?.().forEach((track) => track.stop());
  state.localStream = null;
  state.joinEpoch = "";
  state.joinEventId = "";
  state.joinedAtMs = 0;
  state.lastHeartbeatAt = 0;
  setStatus("idle");
}

async function sendMembershipHeartbeat(force = false) {
  if (state.status !== "joined" || !state.localStream || !state.joinEpoch) return null;
  if (!force && Date.now() - Number(state.lastHeartbeatAt || 0) < MEMBERSHIP_HEARTBEAT_MS) return null;
  state.lastHeartbeatAt = Date.now();
  return sendSignal("membership", {
    joined: true,
    heartbeat: true,
    call_id: `voice_lab_room_${state.roomId}`,
    join_epoch: state.joinEpoch,
    join_event_id: state.joinEventId,
  });
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = window.setInterval(() => {
    void pollRoom();
  }, POLL_MS);
}

function stopPolling() {
  if (!state.pollTimer) return;
  window.clearInterval(state.pollTimer);
  state.pollTimer = 0;
}

async function pollRoom() {
  if (state.pollBusy) return;
  state.pollBusy = true;
  try {
    const room = await postRoom("presence", { timeoutMs: 6000 });
    if (state.status === "joined") await sendMembershipHeartbeat(false);
    await processRoom(room);
  } catch (error) {
    logVoice("room-poll-error", {
      accepted: false,
      ignored: true,
      ignoreReason: summarizeError(error),
    });
  } finally {
    state.pollBusy = false;
    render();
  }
}

async function processRoom(room = state.room) {
  if (!room?.id) return;
  state.processing = state.processing.then(async () => {
    const events = Array.isArray(room.events) ? room.events : [];
    for (const event of events) {
      if (!event?.id || state.processedEventIds.has(event.id)) continue;
      if (event.kind !== SIGNAL_KIND) continue;
      const payload = signalPayload(event);
      if (!payload) continue;
      await handleSignalEvent(event, payload, room);
      state.processedEventIds.add(event.id);
    }
    if (state.processedEventIds.size > 240) {
      state.processedEventIds = new Set(Array.from(state.processedEventIds).slice(-160));
    }
    if (state.status === "joined") await syncPeers(room);
  }).catch((error) => {
    logVoice("room-processing-error", {
      accepted: false,
      ignored: true,
      ignoreReason: summarizeError(error),
    });
  });
  return state.processing;
}

async function handleSignalEvent(event, payload, room) {
  const fromDeviceId = String(payload.from_device_id || "");
  const toDeviceId = String(payload.to_device_id || "");
  if (!fromDeviceId || fromDeviceId === state.localDeviceId) return true;
  if (payload.room_id && payload.room_id !== room.id) {
    logVoice("event-ignored-target-mismatch", {
      payload,
      accepted: false,
      ignored: true,
      ignoreReason: "room-mismatch",
    });
    return true;
  }
  if (payload.type === "join" || payload.type === "membership") {
    logVoice("remote-participant-joined", {
      payload,
      accepted: true,
      peerDeviceId: fromDeviceId,
    });
    return true;
  }
  if (payload.type === "leave" || payload.type === "hangup") {
    const peer = state.peers.get(fromDeviceId);
    if (peer && sharedVoiceSignalMatchesRemoteMembership(payload, peer)) {
      closePeer(fromDeviceId, payload.type);
    }
    logVoice("remote-participant-left", {
      payload,
      accepted: true,
      peerDeviceId: fromDeviceId,
    });
    return true;
  }
  if (!["offer", "answer", "ice-candidate", "mute"].includes(payload.type)) return true;
  if (state.status !== "joined" || !state.localStream) {
    logVoice("event-ignored-local-not-joined", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: fromDeviceId,
      ignoreReason: "local-not-joined",
    });
    return true;
  }
  if (!sharedVoiceSignalIsFresh(event, Date.now(), STALE_MS) || eventBeforeCurrentJoin(event, payload)) {
    logVoice("stale-event-ignored", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: fromDeviceId,
      ignoreReason: "stale-or-before-local-join",
    });
    return true;
  }
  if (toDeviceId !== state.localDeviceId) {
    logVoice("event-ignored-target-mismatch", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: fromDeviceId,
      ignoreReason: "target-device-mismatch",
    });
    return true;
  }
  if (!sharedVoiceSignalTargetsLocalMembership(payload, localMembership())) {
    logVoice("event-ignored-epoch-mismatch", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: fromDeviceId,
      ignoreReason: "target-epoch-mismatch",
    });
    return true;
  }
  const membership = voiceMemberships(room).get(fromDeviceId) || {};
  const peer = ensurePeer({
    deviceId: fromDeviceId,
    clientId: payload.from_client_id || "",
    userId: payload.from_user_id || "",
    label: peerLabel(fromDeviceId, room),
    joinEpoch: membership.joinEpoch || payload.join_epoch || "",
    joinEventId: membership.joinEventId || payload.join_event_id || "",
    callId: payload.call_id || "",
  });
  if (!peer) return true;
  if (!sharedVoiceSignalMatchesRemoteMembership(payload, peer)) {
    logVoice("event-ignored-epoch-mismatch", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: fromDeviceId,
      ignoreReason: "remote-epoch-mismatch",
    });
    return true;
  }
  if (payload.call_id && peer.callId && payload.call_id !== peer.callId && payload.type !== "offer") {
    logVoice("event-ignored-target-mismatch", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: fromDeviceId,
      ignoreReason: "call-id-mismatch",
    });
    return true;
  }
  if (payload.type === "offer") return handleOffer(peer, payload);
  if (payload.type === "answer") return handleAnswer(peer, payload);
  if (payload.type === "ice-candidate") return handleIce(peer, payload);
  if (payload.type === "mute") {
    peer.muted = Boolean(payload.muted);
    logVoice("mute-received", { payload, accepted: true, peerDeviceId: fromDeviceId });
  }
  return true;
}

function peerLabel(deviceId, room = state.room) {
  const presence = (Array.isArray(room?.presence) ? room.presence : []).find((entry) => entry.device_id === deviceId);
  return presence?.user_label && presence?.label
    ? `${presence.user_label} / ${presence.label}`
    : presence?.user_label || presence?.label || deviceId;
}

async function syncPeers(room = state.room) {
  if (state.status !== "joined" || !state.localStream || !room?.id) return;
  const memberships = voiceMemberships(room);
  for (const [deviceId, peer] of Array.from(state.peers.entries())) {
    const membership = memberships.get(deviceId);
    if (!membership || (peer.joinEpoch && membership.joinEpoch && peer.joinEpoch !== membership.joinEpoch)) {
      closePeer(deviceId, "membership-expired");
    }
  }
  for (const [deviceId, membership] of memberships.entries()) {
    if (!deviceId || deviceId === state.localDeviceId) continue;
    const peer = ensurePeer({
      deviceId,
      clientId: membership.payload?.from_client_id || "",
      userId: membership.userId || "",
      label: peerLabel(deviceId, room),
      joinEpoch: membership.joinEpoch || "",
      joinEventId: membership.joinEventId || "",
    });
    if (!peer) continue;
    if (sharedVoiceShouldInitiateRoomOffer(state.localDeviceId, deviceId) && !peer.offerSentForCallId && !peer.makingOffer) {
      await makeOffer(peer);
    }
  }
}

function callIdForPeer(peer) {
  const pair = [
    { deviceId: state.localDeviceId, joinEpoch: state.joinEpoch },
    { deviceId: peer.deviceId, joinEpoch: peer.joinEpoch },
  ].sort((a, b) => a.deviceId.localeCompare(b.deviceId));
  return `voice_lab_${state.roomId}_${pair[0].deviceId}_${pair[0].joinEpoch}_${pair[1].deviceId}_${pair[1].joinEpoch}`
    .replace(/[^a-z0-9_-]+/gi, "-")
    .slice(0, 180);
}

function ensurePeer(details) {
  if (state.status !== "joined" || !state.localStream || !details.deviceId || details.deviceId === state.localDeviceId) return null;
  const existing = state.peers.get(details.deviceId);
  if (existing && details.joinEpoch && existing.joinEpoch && existing.joinEpoch !== details.joinEpoch) {
    closePeer(details.deviceId, "remote-rejoined");
  }
  let peer = state.peers.get(details.deviceId);
  if (!peer) {
    peer = {
      deviceId: details.deviceId,
      clientId: details.clientId || "",
      userId: details.userId || "",
      label: details.label || details.deviceId,
      joinEpoch: details.joinEpoch || "",
      joinEventId: details.joinEventId || "",
      callId: details.callId || "",
      pc: null,
      pendingIceCandidates: [],
      remoteStream: null,
      audioElement: null,
      makingOffer: false,
      ignoreOffer: false,
      polite: String(state.localDeviceId) > String(details.deviceId),
      offerSentForCallId: "",
      muted: false,
    };
    state.peers.set(details.deviceId, peer);
  }
  peer.clientId = details.clientId || peer.clientId || "";
  peer.userId = details.userId || peer.userId || "";
  peer.label = details.label || peer.label || details.deviceId;
  peer.joinEpoch = details.joinEpoch || peer.joinEpoch || "";
  peer.joinEventId = details.joinEventId || peer.joinEventId || "";
  peer.callId = details.callId || peer.callId || "";
  peer.polite = String(state.localDeviceId) > String(details.deviceId);
  if (!peer.pc) createPeerConnection(peer);
  return peer;
}

function createPeerConnection(peer) {
  const pc = new RTCPeerConnection({
    iceServers: iceServers(),
    bundlePolicy: "max-bundle",
    rtcpMuxPolicy: "require",
  });
  peer.pc = pc;
  state.localStream.getAudioTracks().forEach((track) => pc.addTrack(track, state.localStream));
  pc.addEventListener("icecandidate", (event) => {
    if (!event.candidate) return;
    const candidate = event.candidate.toJSON ? event.candidate.toJSON() : event.candidate;
    void sendPeerSignal(peer, "ice-candidate", {
      candidate: JSON.stringify(candidate),
    }).catch((error) => {
      logVoice("ice-event-publish", {
        accepted: false,
        ignored: true,
        peerDeviceId: peer.deviceId,
        callId: peer.callId,
        ignoreReason: summarizeError(error),
      });
    });
  });
  pc.addEventListener("track", (event) => {
    const stream = event.streams?.[0] || peer.remoteStream || new MediaStream();
    if (!event.streams?.[0] && event.track && !stream.getTracks().includes(event.track)) stream.addTrack(event.track);
    peer.remoteStream = stream;
    ensurePeerAudio(peer);
    render();
  });
  const updateStatus = () => {
    peer.status = pc.connectionState || pc.iceConnectionState || "";
    render();
  };
  pc.addEventListener("connectionstatechange", updateStatus);
  pc.addEventListener("iceconnectionstatechange", updateStatus);
  logVoice("peer-connection-created", {
    accepted: true,
    peerDeviceId: peer.deviceId,
    callId: peer.callId,
  });
  render();
  return pc;
}

function ensurePeerAudio(peer) {
  if (!peer.remoteStream || !els.remoteAudioList) return;
  let row = peer.audioRow || null;
  let audio = peer.audioElement || null;
  if (!row) {
    row = document.createElement("div");
    row.className = "remote-audio-row";
    const label = document.createElement("span");
    label.textContent = peer.deviceId;
    audio = document.createElement("audio");
    audio.controls = true;
    audio.autoplay = true;
    audio.playsInline = true;
    row.append(label, audio);
    els.remoteAudioList.append(row);
    peer.audioRow = row;
    peer.audioElement = audio;
  }
  if (audio && audio.srcObject !== peer.remoteStream) audio.srcObject = peer.remoteStream;
  audio?.play?.().catch(() => {});
}

function closePeer(deviceId, reason = "closed") {
  const peer = state.peers.get(deviceId);
  if (!peer) return;
  peer.pc?.close?.();
  if (peer.audioElement) peer.audioElement.srcObject = null;
  peer.audioRow?.remove?.();
  state.peers.delete(deviceId);
  logVoice("peer-connection-closed", {
    accepted: true,
    peerDeviceId: deviceId,
    callId: peer.callId,
    ignoreReason: reason,
  });
  render();
}

function closeAllPeers(reason = "closed") {
  for (const deviceId of Array.from(state.peers.keys())) closePeer(deviceId, reason);
}

async function makeOffer(peer) {
  if (!peer?.pc || state.status !== "joined") return;
  peer.callId = peer.callId || callIdForPeer(peer);
  peer.makingOffer = true;
  try {
    const offer = await peer.pc.createOffer({ offerToReceiveAudio: true });
    await peer.pc.setLocalDescription(offer);
    await sendPeerSignal(peer, "offer", { sdp: peer.pc.localDescription?.sdp || offer.sdp || "" });
    peer.offerSentForCallId = peer.callId;
  } finally {
    peer.makingOffer = false;
  }
}

async function handleOffer(peer, payload) {
  const pc = peer.pc;
  if (!pc) return true;
  if (!peer.callId || peer.callId !== payload.call_id) peer.callId = payload.call_id || peer.callId || callIdForPeer(peer);
  logVoice("offer-received", {
    payload,
    accepted: true,
    peerDeviceId: peer.deviceId,
    callId: peer.callId,
  });
  const offerCollision = peer.makingOffer || pc.signalingState !== "stable";
  peer.ignoreOffer = !peer.polite && offerCollision;
  if (peer.ignoreOffer) {
    logVoice("event-ignored-target-mismatch", {
      payload,
      accepted: false,
      ignored: true,
      peerDeviceId: peer.deviceId,
      callId: peer.callId,
      ignoreReason: "offer-collision",
    });
    return true;
  }
  if (offerCollision) await pc.setLocalDescription({ type: "rollback" });
  await pc.setRemoteDescription({ type: "offer", sdp: String(payload.sdp || "") });
  await flushIce(peer);
  const answer = await pc.createAnswer();
  await pc.setLocalDescription(answer);
  await sendPeerSignal(peer, "answer", { sdp: pc.localDescription?.sdp || answer.sdp || "" });
  return true;
}

async function handleAnswer(peer, payload) {
  const pc = peer.pc;
  if (!pc) return true;
  logVoice("answer-received", {
    payload,
    accepted: true,
    peerDeviceId: peer.deviceId,
    callId: peer.callId,
  });
  if (pc.signalingState !== "stable") {
    await pc.setRemoteDescription({ type: "answer", sdp: String(payload.sdp || "") });
    await flushIce(peer);
  }
  return true;
}

async function handleIce(peer, payload) {
  logVoice("ice-received", {
    payload,
    accepted: true,
    peerDeviceId: peer.deviceId,
    callId: peer.callId,
  });
  try {
    const candidate = typeof payload.candidate === "string" ? JSON.parse(payload.candidate) : payload.candidate;
    await addIce(peer, candidate);
  } catch (error) {
    if (!peer.ignoreOffer) throw error;
  }
  return true;
}

async function addIce(peer, candidate) {
  if (!peer?.pc || !candidate) return;
  if (!peer.pc.remoteDescription?.type) {
    peer.pendingIceCandidates.push(candidate);
    if (peer.pendingIceCandidates.length > 80) peer.pendingIceCandidates.splice(0, peer.pendingIceCandidates.length - 80);
    return;
  }
  await peer.pc.addIceCandidate(candidate);
}

async function flushIce(peer) {
  if (!peer?.pc?.remoteDescription?.type || !peer.pendingIceCandidates.length) return;
  const pending = peer.pendingIceCandidates.splice(0);
  for (const candidate of pending) await peer.pc.addIceCandidate(candidate);
}

async function sendPeerSignal(peer, type, details = {}) {
  if (!peer?.deviceId) throw new Error("peer is missing");
  peer.callId = peer.callId || details.call_id || callIdForPeer(peer);
  return sendSignal(type, {
    ...details,
    call_id: peer.callId,
    to_device_id: peer.deviceId,
    join_epoch: state.joinEpoch,
    join_event_id: state.joinEventId,
    target_join_epoch: peer.joinEpoch,
    target_join_event_id: peer.joinEventId,
  });
}

function setStatus(status) {
  state.status = status;
  render();
}

function renderParticipants() {
  if (!els.participantList) return;
  const room = state.room;
  const memberships = voiceMemberships(room);
  const presence = Array.isArray(room?.presence) ? room.presence : [];
  const ids = new Set([...presence.map((entry) => entry.device_id), ...memberships.keys()]);
  const rows = Array.from(ids).filter(Boolean).sort().map((deviceId) => {
    const entry = presence.find((item) => item.device_id === deviceId) || {};
    const membership = memberships.get(deviceId);
    const li = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = deviceId === state.localDeviceId ? `${deviceId} (local)` : deviceId;
    const meta = document.createElement("span");
    const joined = membership ? `joined ${membership.joinEpoch || "epoch?"}` : "not in voice";
    meta.textContent = `${entry.user_label || "user"} / ${entry.label || "browser"} / ${joined}`;
    li.append(title, meta);
    return li;
  });
  if (!rows.length) {
    const li = document.createElement("li");
    li.textContent = "No participants seen yet.";
    rows.push(li);
  }
  els.participantList.replaceChildren(...rows);
}

function renderLogs() {
  if (!els.eventLog) return;
  const rows = state.logs.slice().reverse().map((item) => {
    const li = document.createElement("li");
    const head = document.createElement("strong");
    head.textContent = `${item.eventType} ${item.accepted ? "accepted" : "ignored"}`;
    const meta = document.createElement("span");
    meta.textContent = JSON.stringify({
      roomId: item.roomId,
      localDeviceId: item.localDeviceId,
      localClientId: item.localClientId,
      localMembershipState: item.localMembershipState,
      localJoinEpoch: item.localJoinEpoch,
      fromDeviceId: item.fromDeviceId,
      toDeviceId: item.toDeviceId,
      peerDeviceId: item.peerDeviceId,
      callId: item.callId,
      ignoreReason: item.ignoreReason,
    });
    li.append(head, meta);
    return li;
  });
  els.eventLog.replaceChildren(...rows);
}

function renderStatePanel() {
  if (!els.statePanel) return;
  const peers = Array.from(state.peers.values()).map((peer) => ({
    deviceId: peer.deviceId,
    clientId: peer.clientId,
    joinEpoch: peer.joinEpoch,
    callId: peer.callId,
    polite: peer.polite,
    pc: peer.pc ? {
      signalingState: peer.pc.signalingState,
      connectionState: peer.pc.connectionState,
      iceConnectionState: peer.pc.iceConnectionState,
    } : null,
    pendingIceCandidates: peer.pendingIceCandidates.length,
  }));
  els.statePanel.textContent = JSON.stringify({
    roomId: state.roomId,
    status: state.status,
    localDeviceId: state.localDeviceId,
    localClientId: state.localClientId,
    joinEpoch: state.joinEpoch,
    joinEventId: state.joinEventId,
    joinedAtMs: state.joinedAtMs,
    hasLocalStream: Boolean(state.localStream),
    peerCount: peers.length,
    peers,
    roomEventCount: Array.isArray(state.room?.events) ? state.room.events.length : 0,
  }, null, 2);
}

function render() {
  if (els.roomInput && cleanRoomId(els.roomInput.value) !== state.roomId && state.status !== "idle") {
    els.roomInput.value = state.roomId;
  }
  if (els.localDeviceId) els.localDeviceId.textContent = state.localDeviceId;
  if (els.localClientId) els.localClientId.textContent = state.localClientId;
  if (els.authState) {
    if (state.auth?.authenticated) {
      els.authState.textContent = `signed in as ${state.auth.user?.email || state.auth.user?.id || "user"}`;
    } else {
      els.authState.textContent = state.auth?.error || "sign in on /home before using the room endpoint";
    }
  }
  if (els.joinButton) els.joinButton.disabled = state.status !== "idle" || !state.auth?.authenticated;
  if (els.leaveButton) els.leaveButton.disabled = !["joining", "joined", "reconnecting"].includes(state.status);
  renderParticipants();
  renderStatePanel();
  renderLogs();
}

function restoreRoomId() {
  const params = new URLSearchParams(window.location.search);
  const fromUrl = params.get("room") || params.get("room_id") || "";
  let stored = "";
  try {
    stored = localStorage.getItem(VOICE_LAB_ROOM_STORAGE_KEY) || "";
  } catch {
    stored = "";
  }
  const roomId = cleanRoomId(fromUrl || stored || els.roomInput?.value || "voice-lab");
  state.roomId = roomId;
  if (els.roomInput) els.roomInput.value = roomId;
}

async function init() {
  restoreRoomId();
  render();
  els.joinButton?.addEventListener("click", () => void joinVoice());
  els.leaveButton?.addEventListener("click", () => void leaveVoice("local-leave"));
  els.roomInput?.addEventListener("change", () => {
    if (state.status === "idle") {
      state.roomId = currentRoomId();
      state.room = null;
      state.processedEventIds = new Set();
      void pollRoom();
    }
    render();
  });
  window.addEventListener("pagehide", () => {
    if (state.status === "joined" && state.joinEpoch) {
      sendSignalKeepalive("leave", {
        reason: "pagehide",
        call_id: `voice_lab_room_${state.roomId}`,
        join_epoch: state.joinEpoch,
        join_event_id: state.joinEventId,
      });
      closeAllPeers("pagehide");
      state.localStream?.getTracks?.().forEach((track) => track.stop());
    }
  });
  await Promise.all([loadSession(), loadConfig()]);
  if (state.auth?.authenticated) {
    await pollRoom();
    startPolling();
  }
  render();
}

void init();
