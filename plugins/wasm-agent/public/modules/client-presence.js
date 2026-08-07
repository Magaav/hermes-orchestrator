import { executeClientObservability } from "./client-observability.js";
import { masterFrontierExplicitProtocol } from "./master-frontier/source-investigation.js?v=20260806-frontier-protocol1";

const CLIENT_ID_KEY = "wasmAgent.liveClientId.v1";
const POLL_MS = 15000;

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
    return ["observe.status", "observe.analytics.on_demand", "control.widget.open", "control.browser.navigate", "control.update.apply", "control.reload"];
  }
  if (runtimeType() === "android-kotlin") {
    return ["observe.status", "observe.analytics.on_demand", "observe.cdp.on_demand", "control.navigate", "control.reload"];
  }
  return ["observe.status", "observe.analytics.on_demand", "observe.cdp.external_on_demand", "control.navigate", "control.reload"];
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
  if (type.startsWith("observability_")) return executeClientObservability(type, payload);
  if (type === "status") return { ok: true, runtime_type: runtimeType(), route: location.href, title: document.title, visibility: document.visibilityState, ui: uiSummary() };
  if (type === "open_widget") {
    if (typeof controls.openWidget !== "function") return { ok: false, error: "widget_control_unavailable" };
    const widgetId = String(payload.widget_id || payload.widgetId || "").trim();
    await controls.openWidget(widgetId);
    return { ok: true, widget_id: widgetId, opened: true };
  }
  if (type === "browser_navigate") {
    if (runtimeType() !== "electron" || !window.wasmAgentNative?.webSurfaces?.invoke) return { ok: false, error: "native_browser_unavailable" };
    const url = new URL(String(payload.url || ""));
    if (url.protocol !== "https:") return { ok: false, error: "navigation_protocol_denied" };
    const surface = await window.wasmAgentNative.webSurfaces.invoke("navigate", { id: "browser", url: url.href });
    return { ok: true, url: url.href, surface };
  }
  if (type === "apply_windows_update") {
    if (runtimeType() !== "electron" || typeof controls.applyWindowsUpdate !== "function") return { ok: false, error: "windows_update_control_unavailable" };
    return controls.applyWindowsUpdate(payload);
  }
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
  const query = new URLSearchParams({
    device_id: clientId(),
    runtime_type: runtimeType(),
    platform: navigator.userAgentData?.platform || navigator.platform || "web",
    route: location.href,
    title: document.title,
    visibility: document.visibilityState,
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
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      await poll(controls).catch(() => {});
      schedule();
    }, document.hidden ? POLL_MS * 2 : POLL_MS);
  };
  void poll(controls).finally(schedule);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) void poll(controls).catch(() => {}); }, { passive: true });
  return { started: true, runtime_type: runtimeType(), client_id: clientId() };
}

export { capabilities as liveClientCapabilities, clientId as liveClientId, runtimeType as liveClientRuntimeType, uiSummary as liveClientUiSummary };
