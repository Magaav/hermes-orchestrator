import { executeClientObservability } from "./client-observability.js?v=20260820-native-input-receipt2";
import { masterFrontierExplicitProtocol } from "./master-frontier/source-investigation.js?v=20260806-frontier-protocol1";

const CLIENT_ID_KEY = "wasmAgent.liveClientId.v1";
const ELECTRON_ACTIVE_POLL_MS = 2000;
const ELECTRON_BACKGROUND_POLL_MS = 10000;
const WEB_ACTIVE_POLL_MS = 15000;
let nativeWebSurfaceCapabilities = null;
let nativeWebSurfaceCapabilityPromise = null;

async function primeNativeWebSurfaceCapabilities() {
  if (nativeWebSurfaceCapabilityPromise) return nativeWebSurfaceCapabilityPromise;
  if (runtimeType() !== "electron" || typeof window.wasmAgentNative?.webSurfaces?.invoke !== "function") {
    nativeWebSurfaceCapabilities = new Set();
    return [];
  }
  nativeWebSurfaceCapabilityPromise = window.wasmAgentNative.webSurfaces.invoke("capabilities", {})
    .then((manifest) => {
      nativeWebSurfaceCapabilities = new Set(Array.isArray(manifest?.capabilities) ? manifest.capabilities : []);
      return [...nativeWebSurfaceCapabilities];
    })
    .catch(() => {
      nativeWebSurfaceCapabilities = new Set();
      return [];
    });
  return nativeWebSurfaceCapabilityPromise;
}

function hasNativeWebSurfaceCapability(value) {
  return nativeWebSurfaceCapabilities?.has(value) === true;
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
    const values = ["observe.status", "observe.analytics.on_demand", "observe.browser.inspect", "control.widget.open", "control.space.open", "control.browser.navigate", "control.navigate", "control.update.apply", "control.reload"];
    if (hasNativeWebSurfaceCapability("web_surface.input_receipt")) values.push("control.browser.input_receipt");
    if (hasNativeWebSurfaceCapability("web_surface.pointer.dispatch")) values.push("control.browser.pointer.dispatch");
    if (hasNativeWebSurfaceCapability("web_surface.javascript.execute.unrestricted")) values.push("control.browser.javascript.execute.unrestricted");
    return values;
  }
  if (runtimeType() === "android-kotlin") {
    return ["observe.status", "observe.analytics.on_demand", "observe.cdp.on_demand", "control.space.open", "control.navigate", "control.reload"];
  }
  return ["observe.status", "observe.analytics.on_demand", "observe.cdp.external_on_demand", "control.space.open", "control.navigate", "control.reload"];
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
    if (!widgetId) return { ok: false, error: "invalid_widget_id" };
    const opened = await controls.openWidget(widgetId);
    return { ok: true, widget_id: widgetId, opened: true, ...(opened?.alreadyOpen === true ? { already_open: true } : {}) };
  }
  if (type === "space_open") {
    if (typeof controls.openSpace !== "function") return { ok: false, error: "space_control_unavailable" };
    const reference = String(payload.space || payload.space_id || payload.space_name || "").trim();
    if (!reference) return { ok: false, error: "space_reference_missing" };
    return { ok: true, ...await controls.openSpace(reference), proof: ["client.ack", "client.space.active"] };
  }
  if (type === "browser_navigate") {
    if (runtimeType() !== "electron" || !window.wasmAgentNative?.webSurfaces?.invoke) return { ok: false, error: "native_browser_unavailable" };
    const url = new URL(String(payload.url || ""));
    if (url.protocol !== "https:") return { ok: false, error: "navigation_protocol_denied" };
    const surface = await window.wasmAgentNative.webSurfaces.invoke("navigate", { id: "browser", url: url.href });
    return { ok: true, url: url.href, surface };
  }
  if (type === "browser_input_receipt") {
    if (runtimeType() !== "electron" || !window.wasmAgentNative?.webSurfaces?.invoke) return { ok: false, error: "native_browser_unavailable" };
    if (!hasNativeWebSurfaceCapability("web_surface.input_receipt")) return { ok: false, error: "input_receipt_unsupported" };
    if (typeof payload.enabled !== "boolean") return { ok: false, error: "invalid_input_receipt_state" };
    const surface = await window.wasmAgentNative.webSurfaces.invoke("input-receipt", { id: "browser", enabled: payload.enabled });
    const acknowledged = surface?.inputReceiptEnabled === payload.enabled;
    return {
      ok: acknowledged,
      browser: { id: "browser", input_receipt_state: payload.enabled ? "enabled" : "disabled" },
      proof: acknowledged ? ["native.web_surface.input_receipt_mode"] : [],
    };
  }
  if (type === "browser_pointer_dispatch") {
    if (runtimeType() !== "electron" || !window.wasmAgentNative?.webSurfaces?.invoke) return { ok: false, error: "native_browser_unavailable" };
    if (!hasNativeWebSurfaceCapability("web_surface.pointer.dispatch")) return { ok: false, error: "pointer_dispatch_unsupported" };
    const x = Number(payload.x);
    const y = Number(payload.y);
    const commandId = String(command?.id || "").trim();
    if (!Number.isSafeInteger(x) || !Number.isSafeInteger(y) || x < 0 || y < 0) return { ok: false, error: "invalid_pointer_dispatch_position" };
    if (!commandId || commandId.length > 80 || !/^[a-zA-Z0-9._-]+$/.test(commandId)) return { ok: false, error: "invalid_pointer_dispatch_command_id" };
    const dispatch = await window.wasmAgentNative.webSurfaces.invoke("pointer-dispatch", { id: "browser", x, y, commandId });
    return {
      ok: dispatch?.ok === true && dispatch?.dispatch_accepted === true,
      browser: { id: "browser", pointer_dispatch: dispatch },
      proof: dispatch?.dispatch_accepted === true ? ["native.web_surface.pointer.dispatch.accepted"] : [],
    };
  }
  if (type === "browser_javascript_execute_unrestricted") {
    if (runtimeType() !== "electron" || !window.wasmAgentNative?.webSurfaces?.invoke) return { ok: false, error: "native_browser_unavailable" };
    if (!hasNativeWebSurfaceCapability("web_surface.javascript.execute.unrestricted")) return { ok: false, error: "browser_javascript_execution_unsupported" };
    const source = String(payload.javascript ?? payload.source ?? "");
    const commandId = String(command?.id || "").trim();
    if (!source.trim()) return { ok: false, error: "javascript_source_missing" };
    if (!commandId || commandId.length > 80 || !/^[a-zA-Z0-9._-]+$/.test(commandId)) return { ok: false, error: "invalid_javascript_command_id" };
    const execution = await window.wasmAgentNative.webSurfaces.invoke("javascript-execute-unrestricted", { id: "browser", source, commandId });
    return {
      ok: execution?.ok === true,
      browser: { id: "browser", javascript_execution: execution },
      proof: execution?.ok === true ? ["native.web_surface.javascript.execute.unrestricted"] : [],
    };
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
  const activeSpace = typeof controls.getActiveSpace === "function" ? controls.getActiveSpace() || {} : {};
  const query = new URLSearchParams({
    device_id: clientId(),
    runtime_type: runtimeType(),
    platform: navigator.userAgentData?.platform || navigator.platform || "web",
    route: location.href,
    title: document.title,
    visibility: document.visibilityState,
    space_id: String(activeSpace.id || activeSpace.storage_id || ""),
    space_name: String(activeSpace.display_name || activeSpace.name || ""),
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
  const primed = runtimeType() === "electron" ? primeNativeWebSurfaceCapabilities() : Promise.resolve([]);
  void primed.finally(() => run().finally(schedule));
  document.addEventListener("visibilitychange", () => {
    clearTimeout(timer);
    if (document.hidden) schedule();
    else void run().finally(schedule);
  }, { passive: true });
  return { started: true, runtime_type: runtimeType(), client_id: clientId() };
}

export {
  capabilities as liveClientCapabilities,
  clientId as liveClientId,
  executeClientCommand as executeLiveClientCommand,
  pollDelay as clientPresencePollDelay,
  primeNativeWebSurfaceCapabilities,
  runtimeType as liveClientRuntimeType,
  uiSummary as liveClientUiSummary,
};
