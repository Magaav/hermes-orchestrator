import { executeClientObservability } from "./client-observability.js";
import { masterFrontierExplicitProtocol } from "./master-frontier/source-investigation.js?v=20260806-frontier-protocol1";
import { prepareRuntimeRefresh } from "./runtime-refresh.js?v=20260826-runtime-refresh1";

const CLIENT_ID_KEY = "wasmAgent.liveClientId.v1";
const ELECTRON_ACTIVE_POLL_MS = 2000;
const ELECTRON_BACKGROUND_POLL_MS = 10000;
const WEB_ACTIVE_POLL_MS = 15000;
const ACTIVE_SURFACE_MANIFEST = "active-surface-v1";
function automaticWindowsUpdatePayload(payload = {}) {
  return { ...payload, automatic: true, applyApproved: true };
}

function pollDelay(runtime = runtimeType(), hidden = document.hidden) {
  if (runtime === "electron") return hidden ? ELECTRON_BACKGROUND_POLL_MS : ELECTRON_ACTIVE_POLL_MS;
  return hidden ? WEB_ACTIVE_POLL_MS * 2 : WEB_ACTIVE_POLL_MS;
}

function clientId() {
  const runtime = runtimeType();
  const storageKey = `${CLIENT_ID_KEY}.${runtime}`;
  let value = localStorage.getItem(storageKey) || "";
  if (!value) {
    const prefix = runtime === "electron" ? "electron-renderer" : "pwa";
    value = `${prefix}-${crypto.randomUUID?.() || `${Date.now()}-${Math.random().toString(16).slice(2)}`}`;
    localStorage.setItem(storageKey, value);
  }
  return value;
}

function runtimeType() {
  if (window.wasmAgentNative?.runtime === "electron") return "electron";
  if (window.WasmAgentNative || /(?:^|[?&])native=android(?:&|$)/.test(location.search)) return "android-kotlin";
  return "pwa";
}

function capabilities() {
  if (runtimeType() === "electron") {
    return ["observe.status", "observe.analytics.on_demand", "observe.runtime.diagnose", "observe.spaces.catalog", "control.widget.open", "control.space.open", "control.agent.session.new", "control.agent.prompt.submit", "control.navigate", "control.update.apply", "control.runtime.refresh", "control.reload"];
  }
  if (runtimeType() === "android-kotlin") {
    return ["observe.status", "observe.analytics.on_demand", "observe.spaces.catalog", "observe.cdp.on_demand", "control.space.open", "control.navigate", "control.reload"];
  }
  return ["observe.status", "observe.analytics.on_demand", "observe.spaces.catalog", "observe.cdp.external_on_demand", "control.space.open", "control.navigate", "control.reload"];
}

function submitAgentPrompt(payload = {}, documentRef = globalThis.document) {
  const message = String(payload.message || "").trim();
  if (!message || message.length > 4096) return { ok: false, error: "agent_prompt_invalid" };
  const input = documentRef?.querySelector?.("#agentInput");
  const form = documentRef?.querySelector?.("#agentForm");
  if (!input || !form?.requestSubmit) return { ok: false, error: "agent_prompt_surface_unavailable" };
  const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(input), "value")?.set;
  if (setter) setter.call(input, message);
  else input.value = message;
  input.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText", data: message }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
  if (String(input.value || "") !== message) return { ok: false, error: "agent_prompt_value_unverified" };
  form.requestSubmit();
  return { ok: true, submitted: true, message_chars: message.length, proof: ["client.agent.prompt.submitted"] };
}

function newAgentSession(documentRef = globalThis.document) {
  const button = documentRef?.querySelector?.("#agentNewSessionButton");
  const input = documentRef?.querySelector?.("#agentInput");
  if (!button?.click || !input) return { ok: false, error: "agent_session_surface_unavailable" };
  const before = String(documentRef?.querySelector?.("#agentOverlay")?.dataset?.sessionId || "");
  button.click();
  const after = String(documentRef?.querySelector?.("#agentOverlay")?.dataset?.sessionId || "");
  const inputEmpty = String(input.value || "") === "";
  if (!inputEmpty) return { ok: false, error: "agent_session_new_postcondition_unverified", before, after, input_empty: false };
  return { ok: true, created: true, before, after, input_empty: true, proof: ["client.agent.session.clean"] };
}

function uiSummary() {
  const documentRef = globalThis.document;
  if (!documentRef?.querySelectorAll) return null;
  const values = (selector, read) => Array.from(documentRef.querySelectorAll(selector)).slice(0, 40).map(read).filter(Boolean);
  const storedProtocol = String(localStorage.getItem("wasmAgent.frontierProtocol") || "").trim();
  return {
    canvas_app_ids: values("#appLayer [data-widget-app]", (node) => node.dataset?.widgetApp),
    open_widget_ids: values(".widget[data-widget-id]:not([hidden]):not(.is-minimized)", (node) => node.dataset?.widgetId),
    widget_icons: values(".widget[data-widget-id][data-widget-icon]", (node) => ({ id: node.dataset?.widgetId, icon: node.dataset?.widgetIcon })),
    widget_windows: values(".widget[data-widget-id][data-widget-resize-contract]", (node) => ({
      id: node.dataset?.widgetId,
      resize_contract: node.dataset?.widgetResizeContract,
      inner_paint_contract: node.dataset?.browserGeometryContract || "dom",
    })),
    resize_directions: Array.from(new Set(values(".widget-resize-handle[data-resize-direction]", (node) => node.dataset?.resizeDirection))).sort(),
    frontier_protocol: {
      effective: masterFrontierExplicitProtocol(location.search, storedProtocol),
      stored: storedProtocol ? (storedProtocol.startsWith("explicit:") ? "explicit" : "legacy") : "none",
    },
    shell_overlay: {
      avatar_chat_open: documentRef.querySelector?.("#agentOverlay")?.dataset?.open === "true",
      suppressed_native_widget_ids: values(".widget[data-native-surface-suppressed='true']", (node) => node.dataset?.widgetId),
    },
  };
}

function activeWidgetIds(summary = uiSummary()) {
  return Array.from(new Set((summary?.canvas_app_ids || [])
    .map((value) => String(value || "").trim().slice(0, 80))
    .filter(Boolean))).slice(0, 32);
}

function activeSurface(controls = {}, summary = uiSummary()) {
  const space = typeof controls.getActiveSpace === "function" ? controls.getActiveSpace() || {} : {};
  return {
    manifest: ACTIVE_SURFACE_MANIFEST,
    space_id: String(space.id || space.storage_id || "").slice(0, 120),
    space_name: String(space.display_name || space.name || "").slice(0, 160),
    widget_ids: activeWidgetIds(summary),
  };
}

function unavailableWidget(widgetId, controls = {}, summary = uiSummary()) {
  const surface = activeSurface(controls, summary);
  if (surface.widget_ids.includes(widgetId)) return null;
  return {
    ok: false,
    error: "widget_unavailable_on_active_surface",
    widget_id: widgetId,
    surface,
  };
}

async function postResult(command, result) {
  await fetch("/native/control/result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ device_id: clientId(), command_id: command.id, command_type: command.type, result }),
  });
}

async function executeClientCommand(command, controls = {}) {
  const type = String(command?.type || "");
  const payload = command?.payload || {};
  if (type.startsWith("observability_") || type === "runtime_diagnose") return executeClientObservability(type, payload);
  if (type === "status") return { ok: true, runtime_type: runtimeType(), route: location.href, title: document.title, visibility: document.visibilityState, ui: uiSummary() };
  if (type === "space_catalog") {
    if (typeof controls.getSpaceCatalog !== "function") return { ok: false, error: "space_catalog_unavailable" };
    const catalog = controls.getSpaceCatalog();
    if (catalog?.manifest !== "space-catalog-v1" || !Array.isArray(catalog.spaces)) return { ok: false, error: "space_catalog_invalid" };
    return { ok: true, ...catalog, proof: ["client.space.catalog"] };
  }
  if (type === "open_widget") {
    if (typeof controls.openWidget !== "function") return { ok: false, error: "widget_control_unavailable" };
    const widgetId = String(payload.widget_id || payload.widgetId || "").trim();
    if (!widgetId) return { ok: false, error: "invalid_widget_id" };
    const unavailable = unavailableWidget(widgetId, controls);
    if (unavailable) return unavailable;
    const opened = await controls.openWidget(widgetId);
    const summary = uiSummary();
    const surface = activeSurface(controls, summary);
    const visible = surface.widget_ids.includes(widgetId) && summary?.open_widget_ids?.includes(widgetId);
    if (opened?.opened !== true || !visible) {
      return { ok: false, error: "widget_open_postcondition_unverified", widget_id: widgetId, opened: opened?.opened === true, visible, surface };
    }
    return {
      ok: true, widget_id: widgetId, opened: true, visible: true, surface,
      proof: ["client.widget.visible"],
      ...(opened.alreadyOpen === true ? { already_open: true } : {}),
    };
  }
  if (type === "space_open") {
    if (typeof controls.openSpace !== "function") return { ok: false, error: "space_control_unavailable" };
    const reference = String(payload.space || payload.space_id || payload.space_name || "").trim();
    if (!reference) return { ok: false, error: "space_reference_missing" };
    return { ok: true, ...await controls.openSpace(reference), surface: activeSurface(controls), proof: ["client.ack", "client.space.active"] };
  }
  if (type === "agent_prompt_submit") {
    if (runtimeType() !== "electron") return { ok: false, error: "agent_prompt_control_unavailable" };
    return submitAgentPrompt(payload);
  }
  if (type === "agent_session_new") {
    if (runtimeType() !== "electron") return { ok: false, error: "agent_session_control_unavailable" };
    return newAgentSession();
  }
  if (type === "apply_windows_update") {
    if (runtimeType() !== "electron" || typeof controls.applyWindowsUpdate !== "function") return { ok: false, error: "windows_update_control_unavailable" };
    const result = await controls.applyWindowsUpdate(automaticWindowsUpdatePayload(payload));
    return {
      ...(result && typeof result === "object" ? result : { ok: false, error: "windows_update_result_invalid" }),
      updatePolicy: { mode: "automatic", approval: "preapproved" },
    };
  }
  if (type === "runtime_refresh") return prepareRuntimeRefresh();
  if (type === "reload" || type === "hard_reload" || type === "reload_ignore_cache") {
    setTimeout(() => location.reload(), 50);
    return { ok: true, reloading: true };
  }
  if (type === "navigate") {
    const url = new URL(String(payload.url || ""), location.href);
    if (url.origin !== location.origin) return { ok: false, error: "cross_origin_navigation_denied" };
    setTimeout(() => location.assign(url.href), 50);
    return { ok: true, navigating: true, route: url.href };
  }
  return { ok: false, error: "unsupported_pwa_control_command" };
}

async function poll(controls = {}) {
  const surface = activeSurface(controls);
  const query = new URLSearchParams({
    device_id: clientId(),
    runtime_type: runtimeType(),
    platform: navigator.userAgentData?.platform || navigator.platform || "web",
    route: location.href,
    title: document.title,
    visibility: document.visibilityState,
    space_id: surface.space_id,
    space_name: surface.space_name,
    widget_manifest: surface.manifest,
    widget_ids: surface.widget_ids.join(","),
    capabilities: capabilities().join(","),
  });
  const response = await fetch(`/native/control/poll?${query}`, { headers: { Accept: "application/json" } });
  if (!response.ok) return;
  const payload = await response.json();
  for (const command of payload.commands || []) {
    let result;
    try { result = await executeClientCommand(command, controls); }
    catch (error) { result = { ok: false, error: String(error?.message || error) }; }
    await postResult(command, result);
  }
}

export function startClientPresence(controls = {}) {
  let timer = 0;
  let inFlight = null;
  const run = () => {
    if (!inFlight) inFlight = poll(controls).catch(() => {}).finally(() => { inFlight = null; });
    return inFlight;
  };
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(() => { void run().finally(schedule); }, pollDelay());
  };
  void run().finally(schedule);
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (document.hidden) schedule();
    else void run().finally(schedule);
  }, { passive: true });
  return { started: true, runtime_type: runtimeType(), client_id: clientId() };
}

export {
  automaticWindowsUpdatePayload,
  capabilities as liveClientCapabilities,
  clientId as liveClientId,
  executeClientCommand as executeLiveClientCommand,
  pollDelay as clientPresencePollDelay,
  runtimeType as liveClientRuntimeType,
  submitAgentPrompt as liveClientSubmitAgentPrompt,
  newAgentSession as liveClientNewAgentSession,
  activeWidgetIds as liveClientActiveWidgetIds,
  uiSummary as liveClientUiSummary,
};
