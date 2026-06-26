const ANDROID_APP_BUILD = "20260622-android-responsive31";
const AUTH_USER_STORAGE_KEY = "wasmAgent.authUser.v1";
const CONFIG_STORAGE_KEY = "wasmAgent.clientConfig.v1";
const BOOT_TRACE_LIMIT = 120;
const BOOT_TRACE_LONG_TASK_LIMIT = 60;
const BOOT_TRACE_INPUT_LIMIT = 40;
const BOOT_TRACE_SLOW_RESOURCE_LIMIT = 24;
const ARCHITECTURE_METRIC_LIMIT = 40;
const ARCHITECTURE_DUPLICATE_RENDER_WINDOW_MS = 32;
const BOOTSTRAP_TIMEOUT_MS = 10000;
const FIRST_INPUT_QUIET_MS = 900;
const TRACE_UPLOAD_DEBOUNCE_MS = 1600;
const LITE_FAST_TAP_MOVE_PX = 10;
const NATIVE_OBS_HEARTBEAT_MS = 5000;
const LITE_SPACES_STORAGE_KEY = "wasmAgent.androidLiteSpaces.v1";
const WAO_HEADER_BYTES = 40;
const WAO_TLV_HEADER_BYTES = 8;
const WAO_VERSION = 1;
const WAO_TLV_NULL = 0;
const WAO_TLV_BOOL = 1;
const WAO_TLV_I64 = 2;
const WAO_TLV_F64 = 3;
const WAO_TLV_UTF8 = 4;
const WAO_TLV_BYTES = 5;
const WAO_TLV_JSON = 6;
const WAO_FRAME_TYPES = {
  HELLO: 1,
  DICT: 2,
  EVENT: 3,
  STATE_PATCH: 4,
  COMMAND: 5,
  COMMAND_ACK: 6,
  SNAPSHOT_REQ: 7,
  SNAPSHOT: 8,
  BLOB_CHUNK: 9,
  HEARTBEAT: 10,
  ERROR: 11,
};
const WAO_FRAME_TYPE_NAMES = Object.fromEntries(Object.entries(WAO_FRAME_TYPES).map(([key, value]) => [value, key]));
const WAO_FIELD_IDS = {
  device_id: 1,
  stream: 2,
  type: 3,
  key: 4,
  ts_ms: 5,
  command_id: 6,
  op: 7,
  status: 8,
  priority: 9,
  deadline_ms: 10,
  result_json: 11,
  payload_json: 12,
  reason: 13,
  route: 14,
  build_id: 15,
  app_version: 16,
  runtime: 17,
  seq_start: 18,
  seq_end: 19,
  latency_ms: 20,
  evidence_refs: 21,
  topics: 22,
  cursor: 23,
  token_budget: 24,
  snapshot_json: 25,
  kind: 26,
  schema: 27,
  role: 28,
};
const WAO_FIELD_NAMES = Object.fromEntries(Object.entries(WAO_FIELD_IDS).map(([key, value]) => [value, key]));

const app = document.getElementById("app");
const loginAvatar = document.getElementById("loginAvatar");
const loginButton = document.getElementById("loginButton");
const loginTitle = document.getElementById("loginTitle");
const loginMeta = document.getElementById("loginMeta");
const loginMessage = document.getElementById("loginMessage");
const launcherLogin = document.getElementById("launcherLogin");
let nativeObsSocket = null;
let nativeObsSeq = 1;
let nativeObsHeartbeatTimer = 0;
let traceUploadTimer = 0;
let androidLastInputAt = 0;
let lastBootPhase = "";
let lastBootPhaseAtMs = 0;
let liteFastTapStart = null;
let liteFastTapUntilMs = 0;

const state = {
  config: null,
  authUser: null,
  authChecked: false,
  configChecked: false,
  activePanel: "home",
  appBootstrapPayload: null,
  nativeAppReadyNotified: false,
  shellVisibleAtMs: 0,
  liteInteractionsInstalled: false,
  openModal: "",
  loginOpen: false,
  selectedLiteSpaceId: "",
  localSpaces: [],
  nativeDebugStatus: "",
  wakeWordStatus: "",
};

const bootTrace = {
  schema: "hermes.wasm_agent.client_boot_trace.v1",
  bootId: `boot-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
  startedAt: new Date().toISOString(),
  startedAtMs: performance.now(),
  marks: [],
  fetches: [],
  inputs: [],
  longTasks: [],
  errors: [],
};

const architectureMetrics = {
  renders: Object.create(null),
  renderLastAtMs: Object.create(null),
  fetches: Object.create(null),
  listeners: Object.create(null),
  recentRenderBursts: [],
};

function cleanText(value = "", fallback = "") {
  const text = String(value ?? "").trim();
  return text || String(fallback ?? "").trim();
}

function elapsedMs() {
  return Math.max(0, Math.round(performance.now() - bootTrace.startedAtMs));
}

function clipped(value = "", limit = 500) {
  return cleanText(value, "").slice(0, limit);
}

function redact(value, depth = 0) {
  if (value === null || typeof value === "undefined") return value;
  if (typeof value === "string") return clipped(value);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (depth > 4) return "[depth-limit]";
  if (Array.isArray(value)) return value.slice(0, 30).map((item) => redact(item, depth + 1));
  if (typeof value === "object") {
    const output = {};
    for (const [key, item] of Object.entries(value).slice(0, 80)) {
      const cleanKey = cleanText(key, "").slice(0, 120);
      if (!cleanKey) continue;
      output[cleanKey] = /cookie|token|secret|authorization|credential|password|api[_-]?key/i.test(cleanKey)
        ? "[redacted]"
        : redact(item, depth + 1);
    }
    return output;
  }
  return clipped(String(value));
}

function countArchitectureMetric(map, key) {
  const cleanKey = clipped(key, 160) || "unknown";
  map[cleanKey] = (Number(map[cleanKey]) || 0) + 1;
  return map[cleanKey];
}

function topArchitectureMetrics(map, limit = 12) {
  return Object.entries(map || {})
    .map(([key, count]) => ({ key, count: Number(count) || 0 }))
    .sort((a, b) => b.count - a.count || a.key.localeCompare(b.key))
    .slice(0, limit);
}

function architectureMetricTotal(map) {
  return Object.values(map || {}).reduce((sum, count) => sum + (Number(count) || 0), 0);
}

function architecturePath(url = "") {
  try {
    return new URL(String(url || ""), window.location.href).pathname || "/";
  } catch {
    return cleanText(url, "unknown").split("?")[0] || "unknown";
  }
}

function noteArchitectureRender(name, detail = {}) {
  const key = clipped(name, 120) || "render";
  const now = performance.now();
  const previous = Number(architectureMetrics.renderLastAtMs[key] || 0);
  const count = countArchitectureMetric(architectureMetrics.renders, key);
  architectureMetrics.renderLastAtMs[key] = now;
  if (previous > 0 && now - previous <= ARCHITECTURE_DUPLICATE_RENDER_WINDOW_MS) {
    architectureMetrics.recentRenderBursts.push(redact({
      render: key,
      count,
      delta_ms: Math.max(0, Math.round(now - previous)),
      detail,
      at_ms: elapsedMs(),
    }));
    while (architectureMetrics.recentRenderBursts.length > ARCHITECTURE_METRIC_LIMIT) {
      architectureMetrics.recentRenderBursts.shift();
    }
  }
}

function noteArchitectureFetch(url, entry = {}) {
  const path = architecturePath(url);
  countArchitectureMetric(architectureMetrics.fetches, path);
}

function noteArchitectureListener(target, type, owner = "android_lite") {
  const key = `${cleanText(target, "target")}:${cleanText(type, "event")}:${cleanText(owner, "owner")}`;
  countArchitectureMetric(architectureMetrics.listeners, key);
}

function architectureSnapshot() {
  const renders = topArchitectureMetrics(architectureMetrics.renders);
  const fetches = topArchitectureMetrics(architectureMetrics.fetches);
  const listeners = topArchitectureMetrics(architectureMetrics.listeners);
  return {
    schema: "hermes.wasm_agent.architecture_metrics.v1",
    render_total: architectureMetricTotal(architectureMetrics.renders),
    fetch_total: architectureMetricTotal(architectureMetrics.fetches),
    listener_total: architectureMetricTotal(architectureMetrics.listeners),
    top_renders: renders,
    top_fetches: fetches,
    listeners,
    repeated_fetch_paths: fetches.filter((item) => item.count > 1),
    recent_render_bursts: architectureMetrics.recentRenderBursts.slice(-12),
  };
}

window.__wasmAgentArchitectureMetrics = architectureSnapshot;

function mark(phase, data = {}) {
  const entry = {
    at_ms: elapsedMs(),
    phase: clipped(phase, 120),
    auth_checked: Boolean(state.authChecked),
    config_checked: Boolean(state.configChecked),
    authenticated: Boolean(state.authUser),
    active_panel: cleanText(state.activePanel, "home"),
    data: redact(data),
  };
  lastBootPhase = entry.phase;
  lastBootPhaseAtMs = entry.at_ms;
  bootTrace.marks.push(entry);
  while (bootTrace.marks.length > BOOT_TRACE_LIMIT) bootTrace.marks.shift();
  try {
    performance.mark(`wasm-agent:${entry.phase}`);
  } catch {
    // Performance marks are diagnostic only.
  }
  return entry;
}

function markAt(phase, performanceNowMs, data = {}) {
  const absoluteMs = Number(performanceNowMs || 0);
  const entry = mark(phase, {
    ...data,
    historical_mark: true,
    performance_now_ms: Number.isFinite(absoluteMs) ? Math.round(absoluteMs) : 0,
  });
  if (Number.isFinite(absoluteMs) && absoluteMs > 0) {
    entry.at_ms = Math.round(absoluteMs - bootTrace.startedAtMs);
    lastBootPhaseAtMs = entry.at_ms;
  }
  return entry;
}

function readCached(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || "null");
  } catch {
    return null;
  }
}

function writeCachedAuthUser(user) {
  try {
    if (!user) localStorage.removeItem(AUTH_USER_STORAGE_KEY);
    else localStorage.setItem(AUTH_USER_STORAGE_KEY, JSON.stringify({ user, cached_at: new Date().toISOString() }));
  } catch {
    // Local auth cache is best effort.
  }
}

function nativeShellInfo() {
  const nativeState = (() => {
    try {
      return window.wasmAgentAndroid?.runtimeState?.() || window.wasmAgentAndroid?.state || {};
    } catch {
      return {};
    }
  })();
  const params = new URL(window.location.href).searchParams;
  return {
    native: "android",
    shell: "android-webview",
    isAndroidNativeShell: true,
    hasBridge: Boolean(window.wasmAgentAndroid),
    buildId: cleanText(nativeState?.build?.build_id || params.get("buildId"), ""),
    installDeviceHash: cleanText(nativeState?.install_device_hash || params.get("install_device_hash"), ""),
    nativeCorrelationId: cleanText(params.get("native_correlation_id"), ""),
    androidAuthSession: cleanText(params.get("android_auth_session"), ""),
    platform: "android",
  };
}

function nativeReloadBridge() {
  const bridges = [window.wasmAgentNative, window.WasmAgentNative, window.wasmAgentAndroid];
  return bridges.find((bridge) => typeof bridge?.reload === "function") || null;
}

function deviceId() {
  const shell = nativeShellInfo();
  if (shell.buildId && shell.installDeviceHash) return `android-${shell.buildId}-${shell.installDeviceHash}`;
  if (shell.buildId) return `android-${shell.buildId}`;
  return "android-unknown";
}

function route() {
  return `${window.location.pathname}${window.location.search || ""}`;
}

function queryParam(name, fallback = "") {
  try {
    return cleanText(new URL(window.location.href).searchParams.get(name), fallback);
  } catch {
    return fallback;
  }
}

function flagParam(name) {
  const value = queryParam(name, "").toLowerCase();
  return value === "1" || value === "true" || value === "yes" || value === "on";
}

function perfSafeMode() {
  return Boolean(window.__WASM_AGENT_ANDROID_PERF_SAFE_MODE__ === true || flagParam("perfSafeMode") || flagParam("perf_safe_mode"));
}

function capabilities() {
  return {
    schema: "hermes.wasm_agent.android_control_capabilities.v1",
    build_id: nativeShellInfo().buildId,
    commands: ["get_runtime_snapshot", "get_android_native_ux_report", "probe_input_latency", "probe_space_switch_latency", "upload_diagnostics", "reload"],
    ux_budgeted: true,
    heavy_commands_idle_only: true,
    screenshots_default_enabled: false,
    ui_snapshot_max_controls: 30,
    architecture_metrics: true,
    android_lite_boot: true,
    lite_interactions: true,
    runtime_mode: "debug-lite",
    debug_shell: true,
    perf_safe_mode: perfSafeMode(),
    wake_startup: perfSafeMode() ? "off" : queryParam("wake", "deferred"),
    bridge_diagnostics: perfSafeMode() ? "off" : queryParam("bridgeDiagnostics", "sampled"),
    user_shell_default: "android-lite",
    native_reload: Boolean(nativeReloadBridge()),
    app_build: ANDROID_APP_BUILD,
  };
}

function describeTarget(element) {
  if (!element) return {};
  const rect = element.getBoundingClientRect?.();
  return {
    tag: cleanText(element.tagName, "").toLowerCase(),
    id: cleanText(element.id, ""),
    role: cleanText(element.getAttribute?.("role"), ""),
    aria_label: cleanText(element.getAttribute?.("aria-label"), ""),
    title: cleanText(element.getAttribute?.("title"), ""),
    classes: Array.from(element.classList || []).slice(0, 8),
    data_panel: cleanText(element.dataset?.panel, ""),
    data_widget_id: cleanText(element.dataset?.widgetId, ""),
    rect: rect ? {
      left: Math.round(rect.left),
      top: Math.round(rect.top),
      width: Math.round(rect.width),
      height: Math.round(rect.height),
    } : null,
  };
}

function elementActuallyVisible(element) {
  let current = element;
  while (current && current.nodeType === Node.ELEMENT_NODE) {
    const style = window.getComputedStyle?.(current);
    if (style && (
      style.visibility === "hidden" ||
      style.display === "none" ||
      Number(style.opacity || 1) === 0
    )) return false;
    if (current.hidden || current.getAttribute?.("aria-hidden") === "true") return false;
    current = current.parentElement;
  }
  return true;
}

function visibleControls(limit = 30) {
  const controls = [];
  const seen = new Set();
  const selector = "button,a[href],input,textarea,select,[role='button'],[data-panel],[data-widget-id]";
  for (const element of Array.from(document.querySelectorAll(selector))) {
    if (controls.length >= limit || seen.has(element)) break;
    seen.add(element);
    const rect = element.getBoundingClientRect?.();
    if (!rect || rect.width <= 0 || rect.height <= 0) continue;
    if (!elementActuallyVisible(element)) continue;
    controls.push({
      ...describeTarget(element),
      text: clipped(element.textContent || element.getAttribute?.("aria-label") || element.getAttribute?.("title") || "", 80),
      disabled: Boolean(element.disabled || element.getAttribute?.("aria-disabled") === "true"),
    });
  }
  return controls;
}

function inputPending() {
  try {
    return Boolean(navigator.scheduling?.isInputPending?.({ includeContinuous: true }));
  } catch {
    return false;
  }
}

function markUserInput() {
  androidLastInputAt = Date.now();
}

function recentInput(ms = FIRST_INPUT_QUIET_MS) {
  return androidLastInputAt > 0 && Date.now() - androidLastInputAt < ms;
}

function recordInput(event, type = "") {
  markUserInput();
  const probeCreatedAtMs = Number(event.__wasmAgentProbeCreatedAtMs || 0);
  const reference = probeCreatedAtMs > 0 ? probeCreatedAtMs : Number(event.timeStamp || performance.now());
  const entry = {
    at_ms: elapsedMs(),
    type: clipped(type || event.type || "input", 40),
    event_time_ms: Math.round(event.timeStamp || 0),
    dispatch_delay_ms: Math.max(0, Math.round(performance.now() - reference)),
    dispatch_delay_source: probeCreatedAtMs > 0 ? "probe_created_at" : "event_timeStamp",
    pointer_type: clipped(event.pointerType || "", 40),
    button: Number.isFinite(event.button) ? event.button : null,
    is_trusted: Boolean(event.isTrusted),
    target: describeTarget(event.target),
    app_status: cleanText(app?.dataset?.status, ""),
    app_auth: cleanText(app?.dataset?.auth, ""),
    active_panel: cleanText(state.activePanel, "home"),
  };
  bootTrace.inputs.push(redact(entry));
  while (bootTrace.inputs.length > BOOT_TRACE_INPUT_LIMIT) bootTrace.inputs.shift();
  mark("user_input_seen", entry);
}

function installInputAndLongTaskProbe() {
  ["pointerdown", "pointerup", "click", "touchstart", "touchend"].forEach((type) => {
    window.addEventListener(type, (event) => recordInput(event, type), { capture: true, passive: true });
  });
  if (typeof PerformanceObserver === "function") {
    try {
      const observer = new PerformanceObserver((list) => {
        for (const entry of list.getEntries()) {
          const item = {
            at_ms: Math.round(entry.startTime || 0),
            duration_ms: Math.round(entry.duration || 0),
            name: clipped(entry.name || "longtask"),
            entry_type: clipped(entry.entryType || ""),
            last_mark_phase: clipped(lastBootPhase),
            last_mark_at_ms: Math.round(lastBootPhaseAtMs || 0),
            input_pending: inputPending(),
          };
          bootTrace.longTasks.push(redact(item));
          while (bootTrace.longTasks.length > BOOT_TRACE_LONG_TASK_LIMIT) bootTrace.longTasks.shift();
          if (item.duration_ms >= 100) mark("main_thread_long_task", item);
        }
      });
      observer.observe({ entryTypes: ["longtask"] });
    } catch {
      // Long task timing is optional.
    }
  }
  mark("input_latency_probe_installed");
}

function decorateAccount(user = state.authUser) {
  if (!user || !launcherLogin || !loginAvatar || !loginButton) return;
  const label = cleanText(user.name || user.email, "Account");
  launcherLogin.classList.add("signed-in");
  launcherLogin.classList.remove("needs-config", "error");
  loginAvatar.replaceChildren();
  loginAvatar.textContent = label.slice(0, 1).toUpperCase() || "A";
  loginAvatar.style.backgroundImage = user.picture_url ? `url("${user.picture_url}")` : "";
  loginButton.title = label;
  loginButton.setAttribute("aria-label", `Account ${label}`);
  if (loginTitle) loginTitle.textContent = label;
  if (loginMeta) loginMeta.textContent = user.email || "Google account";
  if (loginMessage) loginMessage.textContent = user.role ? `${user.role} account ${user.id || ""}`.trim() : "";
  const logoutButton = el("logoutButton");
  if (logoutButton) logoutButton.hidden = false;
}

function el(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const node = el(id);
  if (node) node.textContent = cleanText(value, "");
  return node;
}

function setLoginOpen(open) {
  state.loginOpen = Boolean(open);
  if (loginPopover) loginPopover.hidden = !state.loginOpen;
  if (loginButton) loginButton.setAttribute("aria-expanded", state.loginOpen ? "true" : "false");
  mark("android_lite_login_toggled", { open: state.loginOpen });
}

function sectionPayload(name) {
  const sections = state.appBootstrapPayload?.sections && typeof state.appBootstrapPayload.sections === "object"
    ? state.appBootstrapPayload.sections
    : {};
  return sections[name] || state.appBootstrapPayload?.[name] || null;
}

function sectionError(name) {
  const errors = state.appBootstrapPayload?.errors && typeof state.appBootstrapPayload.errors === "object"
    ? state.appBootstrapPayload.errors
    : {};
  return errors[name] || null;
}

function compactJson(value, limit = 1800) {
  let text = "";
  try {
    text = JSON.stringify(redact(value), null, 2);
  } catch {
    text = cleanText(value, "");
  }
  return text.length > limit ? `${text.slice(0, limit)}...` : text;
}

function metric(label, value) {
  const item = document.createElement("div");
  item.className = "metric";
  const labelEl = document.createElement("div");
  labelEl.className = "metric-label";
  labelEl.textContent = cleanText(label, "");
  const valueEl = document.createElement("div");
  valueEl.className = "metric-value";
  valueEl.textContent = cleanText(value, "");
  item.append(labelEl, valueEl);
  return item;
}

function definitionRows(rows = []) {
  return rows.flatMap(([label, value]) => {
    const dt = document.createElement("dt");
    dt.textContent = cleanText(label, "");
    const dd = document.createElement("dd");
    dd.textContent = cleanText(value, "");
    return [dt, dd];
  });
}

function liteCard(title, meta = "", detail = "", className = "") {
  const card = document.createElement("article");
  card.className = cleanText(className, "artifact-card");
  const head = document.createElement("div");
  head.className = "artifact-card-head";
  const name = document.createElement("strong");
  name.textContent = cleanText(title, "Item");
  const info = document.createElement("span");
  info.textContent = cleanText(meta, "");
  head.append(name, info);
  const body = document.createElement("div");
  body.className = "artifact-card-items";
  const row = document.createElement("span");
  row.textContent = cleanText(detail, "");
  body.append(row);
  card.append(head, body);
  return card;
}

function readLiteSpaces() {
  if (state.localSpaces.length) return state.localSpaces;
  try {
    const payload = JSON.parse(localStorage.getItem(LITE_SPACES_STORAGE_KEY) || "[]");
    if (Array.isArray(payload)) {
      state.localSpaces = payload
        .filter((item) => item && typeof item === "object")
        .map((item) => ({
          id: cleanText(item.id, ""),
          title: cleanText(item.title, item.id),
          created_at: cleanText(item.created_at, ""),
          updated_at: cleanText(item.updated_at, ""),
          space_area: item.space_area && typeof item.space_area === "object" ? item.space_area : {},
          local_only: Boolean(item.local_only),
        }))
        .filter((item) => item.id);
    }
  } catch {
    state.localSpaces = [];
  }
  return state.localSpaces;
}

function writeLiteSpaces(spaces = state.localSpaces) {
  state.localSpaces = Array.isArray(spaces) ? spaces : [];
  try {
    localStorage.setItem(LITE_SPACES_STORAGE_KEY, JSON.stringify(state.localSpaces.slice(0, 40)));
  } catch {
    // Local space cache is best effort.
  }
}

function bootstrapSpaces() {
  const payload = sectionPayload("spaces");
  return Array.isArray(payload?.spaces) ? payload.spaces : [];
}

function allLiteSpaces() {
  const byId = new Map();
  for (const space of bootstrapSpaces()) {
    const id = cleanText(space?.id, "");
    if (!id) continue;
    byId.set(id, {
      ...space,
      id,
      title: cleanText(space?.title, id),
    });
  }
  for (const space of readLiteSpaces()) {
    const id = cleanText(space?.id, "");
    if (!id || byId.has(id)) continue;
    byId.set(id, {
      ...space,
      id,
      title: cleanText(space?.title, id),
    });
  }
  return Array.from(byId.values());
}

function updateBootstrapSpaces(spaces = allLiteSpaces()) {
  if (!state.appBootstrapPayload) state.appBootstrapPayload = { sections: {} };
  if (!state.appBootstrapPayload.sections) state.appBootstrapPayload.sections = {};
  const existing = sectionPayload("spaces") || {};
  state.appBootstrapPayload.sections.spaces = {
    ...existing,
    ok: true,
    schema: existing.schema || "hermes.wasm_agent.user_spaces.v1",
    layout_policy: existing.layout_policy || "client-local",
    spaces,
  };
}

function renderLiteSpaceLauncher() {
  noteArchitectureRender("lite.space_launcher");
  const list = el("spaceLauncherList");
  if (!list) return;
  const spaces = allLiteSpaces();
  list.replaceChildren();
  for (const space of spaces) {
    const button = document.createElement("button");
    button.className = "space-launch-button";
    button.type = "button";
    button.dataset.spaceId = space.id;
    button.title = cleanText(space.title, space.id);
    button.setAttribute("aria-label", button.title);
    button.classList.toggle("active", state.selectedLiteSpaceId === space.id);
    const glyph = document.createElement("span");
    glyph.className = "space-launch-glyph user-space-launch-glyph";
    glyph.setAttribute("aria-hidden", "true");
    button.append(glyph);
    list.append(button);
  }
}

function renderConfigLite(spaceId = state.selectedLiteSpaceId) {
  noteArchitectureRender("lite.config", { space_id: spaceId || "home" });
  const details = el("configDetails");
  if (!details) return;
  const space = allLiteSpaces().find((item) => item.id === spaceId) || null;
  setText("configModalSpaceName", space ? cleanText(space.title, space.id) : "space-home");
  const config = state.config || sectionPayload("config") || {};
  const credits = sectionPayload("credits") || {};
  const rows = space
    ? [
        metric("Space", cleanText(space.title, space.id)),
        metric("Space id", cleanText(space.id, "")),
        metric("Layout", cleanText(sectionPayload("spaces")?.layout_policy, "client-local")),
        metric("Created", cleanText(space.created_at, "")),
        metric("Updated", cleanText(space.updated_at, "")),
      ]
    : [
        metric("Account", cleanText(state.authUser?.email || state.authUser?.name, "authenticated")),
        metric("Google", config?.auth?.googleClientIdConfigured === false ? "missing" : "configured"),
        metric("Deployment", cleanText(config?.deployment?.mode, "cloud")),
        metric("Flux", Number.isFinite(Number(credits.balance)) ? `${credits.balance}` : "account"),
        metric("Sections", Object.keys(state.appBootstrapPayload?.sections || {}).join(", ")),
      ];
  details.replaceChildren(...rows);
}

function renderDevicesLite() {
  noteArchitectureRender("lite.devices");
  const list = el("devicesList");
  const status = el("devicesStatus");
  if (!list) return;
  const error = sectionError("devices");
  const payload = sectionPayload("devices") || {};
  const devices = Array.isArray(payload.devices) ? payload.devices : [];
  if (status) {
    status.textContent = error ? "error" : devices.length ? `${devices.length}` : "account";
    status.className = `widget-chip ${error ? "err" : devices.length ? "ok" : ""}`;
  }
  if (error) {
    list.replaceChildren(metric("Devices", cleanText(error.message, "Unavailable")));
    return;
  }
  if (!devices.length) {
    list.replaceChildren(metric("Devices", state.authUser ? "No devices yet" : "Sign in required"));
    return;
  }
  list.replaceChildren(...devices.map((device) => {
    const card = document.createElement("article");
    card.className = `device-card${device.current ? " current" : ""}`;
    const icon = document.createElement("span");
    icon.className = "device-os-icon android";
    icon.textContent = cleanText(device.label, "De").slice(0, 2);
    icon.setAttribute("aria-hidden", "true");
    const copy = document.createElement("div");
    copy.className = "device-card-copy";
    const title = document.createElement("strong");
    title.textContent = cleanText(device.label, "Device");
    const meta = document.createElement("span");
    meta.textContent = [device.current ? "Current" : "", device.main ? "Main" : "", cleanText(device.reachability, "")].filter(Boolean).join(" / ");
    const detail = document.createElement("p");
    detail.textContent = cleanText(device.user_agent || device.id, "");
    copy.append(title, meta, detail);
    const main = document.createElement("button");
    main.className = "device-main-button icon-button";
    main.type = "button";
    main.dataset.deviceId = cleanText(device.id, "");
    main.title = device.main ? "Main device" : `Make ${cleanText(device.label, "device")} main`;
    main.setAttribute("aria-label", main.title);
    main.disabled = Boolean(device.main);
    main.classList.toggle("active", Boolean(device.main));
    const sync = document.createElement("button");
    sync.className = "device-sync-button icon-button";
    sync.type = "button";
    sync.dataset.deviceId = cleanText(device.id, "");
    sync.title = `Sync ${cleanText(device.label, "device")}`;
    sync.setAttribute("aria-label", sync.title);
    card.append(icon, copy, main, sync);
    return card;
  }));
}

function renderFleetLite() {
  noteArchitectureRender("lite.fleet");
  const list = el("fleetList");
  const status = el("fleetStatus");
  if (!list) return;
  const error = sectionError("fleet");
  const payload = sectionPayload("fleet") || {};
  const harnesses = Array.isArray(payload.harnesses) ? payload.harnesses : [];
  const systemNodes = Array.isArray(payload.system_nodes) ? payload.system_nodes : [];
  const nodes = Array.isArray(payload.nodes) ? payload.nodes : [];
  const count = harnesses.length + systemNodes.length + nodes.length;
  if (status) {
    status.textContent = error ? "error" : cleanText(payload.deployment_mode, count ? `${count}` : "local");
    status.className = `widget-chip ${error ? "err" : count ? "ok" : ""}`;
  }
  if (error) {
    list.replaceChildren(metric("Fleet", cleanText(error.message, "Unavailable")));
    return;
  }
  const rows = [];
  for (const item of harnesses) {
    rows.push(liteCard(
      cleanText(item.harness_name, "Agent harness"),
      cleanText(item.lifecycle_state, ""),
      cleanText(item.node_id || item.bridge_url, "Recover from Nodes"),
      "fleet-card"
    ));
  }
  for (const item of systemNodes.concat(nodes)) {
    rows.push(liteCard(
      cleanText(item.node_id, "node"),
      [item.main ? "main" : "", cleanText(item.role, ""), cleanText(item.backend, "")].filter(Boolean).join(" / "),
      cleanText(payload.server_policy, "ownership metadata"),
      `fleet-card${item.main ? " main" : ""}`
    ));
  }
  list.replaceChildren(...(rows.length ? rows : [metric("Fleet", state.authUser ? "No reserved nodes" : "Sign in required")]));
}

function renderArtifactsLite() {
  noteArchitectureRender("lite.artifacts");
  const list = el("artifactList");
  if (!list) return;
  const spaces = allLiteSpaces();
  const devices = Array.isArray(sectionPayload("devices")?.devices) ? sectionPayload("devices").devices : [];
  const sections = Object.keys(state.appBootstrapPayload?.sections || {});
  list.replaceChildren(
    liteCard("spaces/", `${spaces.length + 1} local`, ["Home", ...spaces.map((space) => cleanText(space.title, space.id))].join(", ")),
    liteCard("devices/", `${devices.length} account`, devices.map((device) => cleanText(device.label, device.id)).join(", ") || "account"),
    liteCard("bootstrap/", `${sections.length} sections`, sections.join(", ") || "pending"),
    liteCard("browser-layouts/", "client-local", "positions and widget geometry stay in this WebView")
  );
}

function renderModulesLite(mode = "modules") {
  noteArchitectureRender("lite.modules", { mode });
  const list = el("homeModuleList");
  if (!list) return;
  setText("homeModulesModalTitle", mode === "market" ? "Market" : "Modules");
  const sections = Object.keys(state.appBootstrapPayload?.sections || {});
  const modules = [
    ["spaces", "Spaces", `${allLiteSpaces().length} user spaces`, "Core"],
    ["devices", "Connected Devices", `${(sectionPayload("devices")?.devices || []).length || 0} devices`, "Core"],
    ["fleet", "Fleet", cleanText(sectionPayload("fleet")?.deployment_mode, "local"), "Core"],
    ["artifacts", "Artifacts", "client-local inventory", "Core"],
    ["models", "Models", Array.isArray(sectionPayload("models")?.data) ? `${sectionPayload("models").data.length} models` : "bootstrap"],
    ["readiness", "Readiness", cleanText(sectionPayload("readiness")?.status || sectionPayload("readiness")?.ready, "bootstrap")],
  ];
  if (sections.length) modules.push(["bootstrap", "Bootstrap", sections.join(", "), "Live"]);
  list.replaceChildren(...modules.map(([id, title, detail, status = "On"]) => {
    const card = document.createElement("article");
    card.className = "module-card enabled core";
    card.dataset.moduleId = id;
    const copy = document.createElement("div");
    copy.className = "module-copy";
    const name = document.createElement("strong");
    name.textContent = title;
    const body = document.createElement("p");
    body.textContent = detail;
    const meta = document.createElement("span");
    meta.textContent = status;
    copy.append(name, body, meta);
    const label = document.createElement("label");
    label.className = "module-toggle";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = true;
    input.disabled = true;
    const control = document.createElement("span");
    control.textContent = status;
    label.append(input, control);
    card.append(copy, label);
    return card;
  }));
}

function liteDeviceProfile() {
  const ua = navigator.userAgent || "";
  const platform = /Android/i.test(ua) ? "android" : "unknown";
  return {
    platform,
    os: platform === "android" ? "Android" : "Device",
    arch: /aarch64|arm64/i.test(ua) ? "arm64" : "unknown",
    browser: /Edg\//i.test(ua) ? "edge" : /Firefox/i.test(ua) ? "firefox" : /Chrome|Chromium/i.test(ua) ? "chrome" : "unknown",
    deviceType: /Mobile|Android/i.test(ua) ? "phone" : "unknown",
  };
}

function renderNativeLite() {
  noteArchitectureRender("lite.native");
  const profile = liteDeviceProfile();
  const shell = nativeShellInfo();
  const resolution = state.nativeInstallResolution || null;
  setText("nativeModalSubtitle", `${profile.os} / ${profile.deviceType}`);
  const status = el("nativeInstallStatus");
  if (status) {
    status.textContent = state.nativeInstallStatus || (resolution?.available ? "available" : resolution ? "missing" : "native");
    status.className = `widget-chip ${resolution?.available ? "ok" : resolution ? "err" : ""}`;
  }
  const download = el("nativeDownloadButton");
  if (download) {
    download.textContent = resolution?.available ? "Download" : "Android APK";
    download.disabled = !state.authUser || state.nativeInstallBusy;
    download.classList.toggle("is-busy", Boolean(state.nativeInstallBusy));
  }
  const deviceSummary = el("nativeDeviceSummary");
  if (deviceSummary) {
    const title = document.createElement("h3");
    title.textContent = "Detected Device";
    deviceSummary.replaceChildren(
      title,
      metric("OS", profile.os),
      metric("Device type", profile.deviceType),
      metric("Browser", profile.browser),
      metric("Architecture", profile.arch),
      metric("Bridge", shell.hasBridge ? "available" : "unavailable"),
      metric("Build", shell.buildId || "unknown")
    );
  }
  const packageSummary = el("nativePackageSummary");
  if (packageSummary) {
    const title = document.createElement("h3");
    title.textContent = "Native Installer";
    packageSummary.replaceChildren(
      title,
      metric("Status", resolution ? (resolution.available ? "available" : cleanText(resolution.message, "Native installer not built yet")) : "pending"),
      metric("Kind", cleanText(resolution?.kind, "android-apk")),
      metric("File", cleanText(resolution?.filename, "pending")),
      metric("Build", cleanText(resolution?.buildId || resolution?.buildStatus, "checking"))
    );
  }
  const chooser = el("nativeManualChooser");
  if (chooser) {
    const title = document.createElement("h3");
    title.textContent = "Manual chooser";
    const list = document.createElement("div");
    list.className = "native-choice-list";
    for (const [platform, label] of [["android", "Android"], ["windows", "Windows"], ["macos", "macOS"], ["linux", "Linux"], ["ios", "iOS/iPadOS"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.dataset.nativePlatform = platform;
      list.append(button);
    }
    chooser.replaceChildren(title, list);
  }
}

function nativeDebugRows() {
  const shell = nativeShellInfo();
  const trace = bootTracePayload("native_debug_modal");
  const arch = trace.architecture || architectureSnapshot();
  return [
    ["Bridge", shell.hasBridge ? "available" : "unavailable"],
    ["Build", shell.buildId || "unknown"],
    ["Install hash", shell.installDeviceHash || "unknown"],
    ["Auth", state.authUser ? "authenticated" : "checking"],
    ["Bootstrap", Object.keys(state.appBootstrapPayload?.sections || {}).join(", ") || "pending"],
    ["Long tasks >100ms", `${bootTrace.longTasks.filter((item) => Number(item.duration_ms || 0) >= 100).length}`],
    ["Fetches", `${bootTrace.fetches.length}`],
    ["Architecture", `${arch.render_total || 0} renders / ${arch.listener_total || 0} listeners / ${arch.repeated_fetch_paths?.length || 0} repeated fetch paths`],
    ["Status", state.nativeDebugStatus || "diagnostics"],
    ["Trace", trace.boot_id],
  ];
}

function renderNativeDebugLite() {
  noteArchitectureRender("lite.native_debug");
  setText("nativeDebugMeta", state.nativeDebugStatus || "android-webview-lite");
  const dl = el("nativeDebugState");
  if (dl) dl.replaceChildren(...definitionRows(nativeDebugRows()));
  const output = el("nativeDebugOutput");
  if (output) output.textContent = compactJson(bootTracePayload("native_debug_modal"), 4000);
}

function renderWakeWordLite() {
  noteArchitectureRender("lite.wake_word");
  const shell = nativeShellInfo();
  setText("wakeWordStatus", state.wakeWordStatus || (shell.hasBridge ? "bridge" : "standby"));
  const dl = el("wakeWordState");
  if (dl) {
    let nativeState = {};
    try {
      nativeState = window.wasmAgentAndroid?.runtimeState?.() || window.wasmAgentAndroid?.state || {};
    } catch {
      nativeState = {};
    }
    dl.replaceChildren(...definitionRows([
      ["Bridge", shell.hasBridge ? "available" : "unavailable"],
      ["Build", shell.buildId || "unknown"],
      ["Wake status", state.wakeWordStatus || cleanText(nativeState?.voiceWake?.status || nativeState?.wakeWord?.status, "standby")],
      ["Policy", cleanText(nativeState?.voiceWake?.wakePhrase || nativeState?.wakeWord?.phrase, "alexa")],
      ["Runtime", ANDROID_APP_BUILD],
    ]));
  }
  const output = el("wakeWordOutput");
  if (output) output.textContent = compactJson({
    native_shell: shell,
    state: state.wakeWordStatus || "standby",
    latest_inputs: bootTrace.inputs.slice(-5),
  }, 2400);
}

function renderActiveLiteModal() {
  if (!state.openModal) return;
  renderLiteModal(state.openModal);
}

function renderLiteModal(modalId, reason = "") {
  noteArchitectureRender("lite.modal", { modal_id: modalId, reason });
  if (modalId === "devicesModal") renderDevicesLite();
  else if (modalId === "fleetModal") renderFleetLite();
  else if (modalId === "artifactsModal") renderArtifactsLite();
  else if (modalId === "homeModulesModal") renderModulesLite(reason === "market" ? "market" : "modules");
  else if (modalId === "nativeModal") renderNativeLite();
  else if (modalId === "nativeDebugModal") renderNativeDebugLite();
  else if (modalId === "wakeWordModal") renderWakeWordLite();
  else if (modalId === "configModal") renderConfigLite();
}

function openLiteModal(modalId, reason = "") {
  const modal = el(modalId);
  if (!modal) return false;
  closeLiteModal();
  renderLiteModal(modalId, reason);
  modal.hidden = false;
  state.openModal = modalId;
  if (app) app.dataset.androidLiteModal = modalId;
  mark("android_lite_modal_opened", { modal_id: modalId, reason });
  return true;
}

function closeLiteModal(modalId = state.openModal) {
  const ids = [
    "joinSpaceModal",
    "configModal",
    "artifactsModal",
    "devicesModal",
    "nativeModal",
    "nativeDebugModal",
    "fleetModal",
    "homeModulesModal",
    "wakeWordModal",
  ];
  const targets = modalId ? [modalId] : ids;
  for (const id of targets) {
    const modal = el(id);
    if (modal) modal.hidden = true;
  }
  if (!modalId || modalId === state.openModal) state.openModal = "";
  if (app) delete app.dataset.androidLiteModal;
}

function selectLiteSpace(spaceId) {
  const space = allLiteSpaces().find((item) => item.id === spaceId);
  if (!space) return;
  state.selectedLiteSpaceId = space.id;
  state.activePanel = space.id;
  if (app) {
    app.dataset.panel = space.id;
    app.dataset.panelKind = "user-space";
  }
  setText("spaceLabel", cleanText(space.title, space.id));
  renderLiteSpaceLauncher();
  closeLiteModal();
  mark("android_lite_space_selected", { space_id: space.id });
}

function createLiteSpace() {
  const spaces = allLiteSpaces();
  const createdAt = new Date().toISOString();
  const space = {
    id: `space_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`,
    title: `Space ${spaces.length + 1}`,
    created_at: createdAt,
    updated_at: createdAt,
    space_area: { width_px: 1000, height_px: 760, distance: 1 },
    local_only: false,
  };
  const nextSpaces = [...spaces, space];
  updateBootstrapSpaces(nextSpaces);
  writeLiteSpaces([...readLiteSpaces().filter((item) => item.id !== space.id), space]);
  state.selectedLiteSpaceId = space.id;
  renderLiteSpaceLauncher();
  renderConfigLite(space.id);
  openLiteModal("configModal", "create_space");
  mark("android_lite_space_created", { space_id: space.id, title: space.title });
  if (state.authUser) {
    void fetchJson("/spaces", {
      method: "POST",
      timeoutMs: 8000,
      body: { action: "replace", spaces: nextSpaces },
    }).then((payload) => {
      if (Array.isArray(payload?.spaces)) {
        state.localSpaces = [];
        try {
          localStorage.removeItem(LITE_SPACES_STORAGE_KEY);
        } catch {
          // Local space cache is best effort.
        }
        updateBootstrapSpaces(payload.spaces);
        renderLiteSpaceLauncher();
        renderActiveLiteModal();
      }
    }).catch((error) => {
      state.nativeDebugStatus = cleanText(error?.message || error, "space save failed");
      mark("android_lite_space_save_failed", { message: state.nativeDebugStatus });
    });
  }
}

function joinCodeFromText(value = "") {
  const text = cleanText(value, "");
  if (!text) return "";
  try {
    const parsed = new URL(text);
    return cleanText(parsed.searchParams.get("join") || parsed.searchParams.get("code") || parsed.pathname.split("/").filter(Boolean).pop(), "");
  } catch {
    return text.replace(/[^A-Za-z0-9_-]/g, "").slice(0, 120);
  }
}

async function joinSpaceLite() {
  const input = el("joinSpaceInput");
  const message = el("joinSpaceMessage");
  const joinCode = joinCodeFromText(input?.value || "");
  if (!joinCode) {
    if (message) message.textContent = "Paste an invite link or join code.";
    return;
  }
  if (message) message.textContent = "Joining...";
  mark("android_lite_join_space_started", { code_present: true });
  try {
    const payload = await fetchJson("/spaces/join", {
      method: "POST",
      timeoutMs: 10000,
      body: { join_code: joinCode },
    });
    const result = payload.spaces || {};
    if (Array.isArray(result.spaces)) {
      state.localSpaces = [];
      updateBootstrapSpaces(result.spaces);
      renderLiteSpaceLauncher();
    }
    if (message) message.textContent = "Joined.";
    mark("android_lite_join_space_finished", { ok: true });
  } catch (error) {
    if (message) message.textContent = cleanText(error?.message || error, "Join failed");
    mark("android_lite_join_space_failed", { message: cleanText(error?.message || error, "") });
  }
}

async function setMainDeviceLite(deviceId) {
  if (!deviceId) return;
  try {
    const payload = await fetchJson("/account/devices/main", {
      method: "POST",
      timeoutMs: 8000,
      body: { device_id: deviceId },
    });
    if (payload?.devices) {
      if (!state.appBootstrapPayload) state.appBootstrapPayload = { sections: {} };
      state.appBootstrapPayload.sections.devices = payload;
    }
    renderDevicesLite();
    mark("android_lite_main_device_set", { device_id: deviceId });
  } catch (error) {
    state.nativeDebugStatus = cleanText(error?.message || error, "device update failed");
    renderNativeDebugLite();
  }
}

async function syncDeviceLite(deviceId = "") {
  const current = deviceId || sectionPayload("devices")?.current_device_id || "";
  if (!current) return;
  try {
    const payload = await fetchJson("/account/devices/sync", {
      method: "POST",
      timeoutMs: 8000,
      body: { device_id: current },
    });
    state.nativeDebugStatus = `sync ${cleanText(payload?.package?.token_id, "ready")}`;
    renderActiveLiteModal();
    mark("android_lite_device_sync_ready", { device_id: current });
  } catch (error) {
    state.nativeDebugStatus = cleanText(error?.message || error, "device sync failed");
    renderActiveLiteModal();
  }
}

async function ensureMainFleetLite() {
  try {
    const payload = await fetchJson("/fleet/nodes/ensure-main", {
      method: "POST",
      timeoutMs: 8000,
      body: {},
    });
    if (!state.appBootstrapPayload) state.appBootstrapPayload = { sections: {} };
    if (!state.appBootstrapPayload.sections) state.appBootstrapPayload.sections = {};
    const fleet = sectionPayload("fleet") || {};
    state.appBootstrapPayload.sections.fleet = {
      ...fleet,
      nodes: Array.isArray(fleet.nodes) ? fleet.nodes : [],
      system_nodes: [payload.node, ...(Array.isArray(fleet.system_nodes) ? fleet.system_nodes.filter((node) => node.node_id !== payload.node?.node_id) : [])].filter(Boolean),
    };
    renderFleetLite();
    mark("android_lite_fleet_main_reserved", { node_id: cleanText(payload?.node?.node_id, "") });
  } catch (error) {
    state.nativeDebugStatus = cleanText(error?.message || error, "fleet update failed");
    renderFleetLite();
  }
}

async function resolveNativeLite(platform = "android") {
  const profile = liteDeviceProfile();
  state.nativeInstallBusy = true;
  state.nativeInstallStatus = "checking";
  renderNativeLite();
  try {
    const payload = await fetchJson("/native/resolve", {
      method: "POST",
      timeoutMs: 8000,
      body: {
        platform,
        arch: profile.arch,
        browser: profile.browser,
        deviceType: profile.deviceType,
      },
    });
    state.nativeInstallResolution = payload;
    state.nativeInstallStatus = payload.available ? "available" : "missing";
    if (payload.available && payload.downloadUrl) window.location.href = payload.downloadUrl;
    mark("android_lite_native_resolved", { platform, available: Boolean(payload.available) });
  } catch (error) {
    state.nativeInstallStatus = "error";
    state.nativeInstallResolution = { available: false, message: cleanText(error?.message || error, "Native installer not built yet") };
    mark("android_lite_native_resolve_failed", { message: state.nativeInstallResolution.message });
  } finally {
    state.nativeInstallBusy = false;
    renderNativeLite();
  }
}

function callAndroidBridgeMethod(methodName, statusLabel = "") {
  const bridge = window.wasmAgentAndroid;
  try {
    if (!bridge?.[methodName]) throw new Error("bridge method unavailable");
    bridge[methodName]();
    state.nativeDebugStatus = statusLabel || methodName;
    state.wakeWordStatus = statusLabel || methodName;
  } catch (error) {
    state.nativeDebugStatus = cleanText(error?.message || error, "bridge method unavailable");
    state.wakeWordStatus = state.nativeDebugStatus;
  }
  mark("android_lite_bridge_action", { method: methodName, status: state.nativeDebugStatus });
  renderActiveLiteModal();
}

async function copyTextLite(text, status = "copied") {
  try {
    await navigator.clipboard.writeText(cleanText(text, ""));
    state.nativeDebugStatus = status;
  } catch {
    state.nativeDebugStatus = "copy failed";
  }
  renderActiveLiteModal();
}

async function shareTextLite(text) {
  try {
    if (navigator.share) {
      await navigator.share({ title: "WASM Agent Android diagnostics", text: cleanText(text, "") });
      state.nativeDebugStatus = "shared";
    } else {
      await copyTextLite(text);
    }
  } catch {
    state.nativeDebugStatus = "share canceled";
  }
  renderActiveLiteModal();
}

function startAndroidLoginLite() {
  try {
    if (window.wasmAgentAndroid?.startGoogleLogin) {
      window.wasmAgentAndroid.startGoogleLogin();
      mark("android_lite_native_google_login_started");
      return true;
    }
  } catch (error) {
    mark("android_lite_native_google_login_failed", { message: cleanText(error?.message || error, "") });
  }
  setLoginOpen(true);
  return false;
}

async function logoutLite() {
  try {
    await fetchJson("/auth/logout", { method: "POST", timeoutMs: 8000, body: {} });
  } catch {
    // Logout still clears local cached auth.
  }
  state.authUser = null;
  state.authChecked = true;
  writeCachedAuthUser(null);
  if (app) {
    app.dataset.auth = "locked";
    app.dataset.status = "ready";
    delete app.dataset.androidPrepaint;
  }
  setLoginOpen(false);
  mark("android_lite_logout_finished");
}

function setAgentOpen(open) {
  const overlay = el("agentOverlay");
  const button = el("agentAvatarButton");
  syncLiteAgentBounds();
  if (overlay) overlay.dataset.open = open ? "true" : "false";
  if (button) button.setAttribute("aria-expanded", open ? "true" : "false");
  mark("android_lite_agent_toggled", { open: Boolean(open) });
}

function syncLiteAgentBounds() {
  const overlay = el("agentOverlay");
  if (!overlay) return;
  overlay.dataset.androidLite = "true";
  const viewport = window.visualViewport;
  const width = Math.max(320, Math.round(viewport?.width || window.innerWidth || document.documentElement.clientWidth || 0));
  const height = Math.max(1, Math.round(viewport?.height || window.innerHeight || document.documentElement.clientHeight || 0));
  overlay.style.setProperty("--agent-app-width", `${width}px`);
  overlay.style.setProperty("--agent-app-height", `${height}px`);
}

function appendAgentMessage(kind, text) {
  const messages = el("agentMessages");
  if (!messages) return;
  const row = document.createElement("div");
  row.className = `agent-message ${kind === "user" ? "user" : "assistant"}`;
  row.textContent = cleanText(text, "");
  messages.append(row);
  messages.scrollTop = messages.scrollHeight;
}

function submitLiteAgentMessage(event) {
  event?.preventDefault?.();
  const input = el("agentInput");
  const value = cleanText(input?.value, "");
  if (!value) return;
  input.value = "";
  appendAgentMessage("user", value);
  const sections = Object.keys(state.appBootstrapPayload?.sections || {});
  appendAgentMessage("assistant", sections.length
    ? `Boot ready: ${sections.join(", ")}.`
    : "Boot shell ready.");
  mark("android_lite_agent_message_submitted", { length: value.length });
}

function closeButtonModalId(id) {
  return {
    closeJoinSpaceButton: "joinSpaceModal",
    cancelJoinSpaceButton: "joinSpaceModal",
    closeConfigModalButton: "configModal",
    closeArtifactsModalButton: "artifactsModal",
    closeDevicesModalButton: "devicesModal",
    closeNativeModalButton: "nativeModal",
    closeNativeDebugButton: "nativeDebugModal",
    closeFleetModalButton: "fleetModal",
    closeHomeModulesModalButton: "homeModulesModal",
    closeWakeWordModalButton: "wakeWordModal",
  }[id] || "";
}

function handleLiteClick(event) {
  if (!event.__wasmAgentLiteFastTapReplay && liteFastTapUntilMs > 0 && performance.now() < liteFastTapUntilMs) {
    event.preventDefault();
    event.stopPropagation();
    return;
  }
  const target = event.target;
  const clickable = target?.closest?.("button,a,#googleSignInButton,#authGateGoogleSignInButton");
  const backdrop = target?.classList?.contains("modal-backdrop") ? target : null;
  if (backdrop?.id) {
    event.preventDefault();
    closeLiteModal(backdrop.id);
    return;
  }
  if (!clickable) {
    if (!target?.closest?.("#launcherLogin")) setLoginOpen(false);
    return;
  }
  const id = cleanText(clickable.id, "");
  if (clickable.disabled || clickable.getAttribute?.("aria-disabled") === "true") return;

  const closeId = closeButtonModalId(id);
  if (closeId) {
    event.preventDefault();
    closeLiteModal(closeId);
    return;
  }

  if (id === "loginButton") {
    event.preventDefault();
    event.stopPropagation();
    setLoginOpen(!state.loginOpen);
    return;
  }
  if (["authGateLoginButton", "googleSignInButton", "authGateGoogleSignInButton"].includes(id)) {
    event.preventDefault();
    event.stopPropagation();
    startAndroidLoginLite();
    return;
  }
  if (id === "logoutButton") {
    event.preventDefault();
    void logoutLite();
    return;
  }
  if (!clickable.closest?.("#launcherLogin")) setLoginOpen(false);

  if (clickable.classList?.contains("launcher-mark") || clickable.dataset?.panel === "home") {
    event.preventDefault();
    state.selectedLiteSpaceId = "";
    state.activePanel = "home";
    if (app) app.dataset.panel = "home";
    setText("spaceLabel", "space-home");
    renderLiteSpaceLauncher();
    closeLiteModal();
    mark("android_lite_home_selected");
    return;
  }
  if (id === "spaceOrganizeButton") {
    event.preventDefault();
    renderLiteSpaceLauncher();
    mark("android_lite_space_launcher_organized");
    return;
  }
  if (id === "addSpaceButton") {
    event.preventDefault();
    createLiteSpace();
    return;
  }
  if (id === "joinSpaceButton") {
    event.preventDefault();
    openLiteModal("joinSpaceModal", "home_join_space");
    window.setTimeout(() => el("joinSpaceInput")?.focus?.(), 0);
    return;
  }
  if (id === "confirmJoinSpaceButton") {
    event.preventDefault();
    void joinSpaceLite();
    return;
  }
  if (id === "homeFleetButton") {
    event.preventDefault();
    openLiteModal("fleetModal", "home_fleet");
    return;
  }
  if (id === "homeDevicesButton") {
    event.preventDefault();
    openLiteModal("devicesModal", "home_devices");
    return;
  }
  if (id === "homeGoNativeButton") {
    event.preventDefault();
    openLiteModal("nativeModal", "home_native");
    return;
  }
  if (id === "homeWakeWordButton") {
    event.preventDefault();
    openLiteModal("wakeWordModal", "home_wake_word");
    return;
  }
  if (id === "homeArtifactsButton") {
    event.preventDefault();
    openLiteModal("artifactsModal", "home_artifacts");
    return;
  }
  if (id === "homeModulesButton" || id === "homeMarketButton") {
    event.preventDefault();
    openLiteModal("homeModulesModal", id === "homeMarketButton" ? "market" : "modules");
    return;
  }
  if (id === "homeDiagnosticsButton") {
    event.preventDefault();
    openLiteModal("nativeDebugModal", "home_diagnostics");
    return;
  }
  if (clickable.classList?.contains("space-launch-button")) {
    event.preventDefault();
    selectLiteSpace(cleanText(clickable.dataset.spaceId, ""));
    return;
  }
  if (id === "devicesSyncButton" || clickable.classList?.contains("device-sync-button")) {
    event.preventDefault();
    void syncDeviceLite(cleanText(clickable.dataset.deviceId, ""));
    return;
  }
  if (clickable.classList?.contains("device-main-button")) {
    event.preventDefault();
    void setMainDeviceLite(cleanText(clickable.dataset.deviceId, ""));
    return;
  }
  if (id === "fleetEnsureMainButton") {
    event.preventDefault();
    void ensureMainFleetLite();
    return;
  }
  if (id === "nativeDownloadButton") {
    event.preventDefault();
    void resolveNativeLite();
    return;
  }
  if (clickable.dataset?.nativePlatform) {
    event.preventDefault();
    void resolveNativeLite(cleanText(clickable.dataset.nativePlatform, "android"));
    return;
  }
  if (id === "nativeDebugCopyButton") {
    event.preventDefault();
    void copyTextLite(compactJson(bootTracePayload("native_debug_copy"), 8000));
    return;
  }
  if (id === "nativeDebugShareButton") {
    event.preventDefault();
    void shareTextLite(compactJson(bootTracePayload("native_debug_share"), 8000));
    return;
  }
  const bridgeActions = {
    nativeDebugRetryButton: ["startGoogleLogin", "retry requested"],
    nativeDebugResetAuthButton: ["resetAuth", "auth reset"],
    nativeDebugClearWebViewButton: ["clearWebViewData", "WebView cleared"],
    nativeDebugClearDiagnosticsButton: ["clearDiagnostics", "diagnostics cleared"],
    nativeDebugEnableVoiceWakeButton: ["enableVoiceWake", "Hermes voice enabled"],
    nativeDebugDisableVoiceWakeButton: ["disableVoiceWake", "Hermes voice disabled"],
    wakeWordRefreshButton: ["runtimeState", "refreshed"],
    wakeWordFalseWakeFetchButton: ["fetchFalseWakes", "false-wakes fetched"],
    wakeWordFalseWakeDrainButton: ["drainFalseWakes", "acked drained"],
    wakeWordRestartButton: ["restartVoiceWake", "listener restarted"],
    wakeWordStartButton: ["enableVoiceWake", "listener enabled"],
    wakeWordStopButton: ["disableVoiceWake", "listener disabled"],
    wakeWordProofStandbyButton: ["proveVoiceWakeStandby", "standby proof requested"],
    wakeWordProofAppButton: ["proveVoiceWakeAppVisible", "app-visible proof requested"],
    wakeWordSessionButton: ["startVoiceWakeTuning", "session started"],
    wakeWordStepDoneButton: ["completeVoiceWakeStep", "step done"],
    wakeWordInstallModelButton: ["installVoiceWakeModel", "model install requested"],
    wakeWordApplyPolicyButton: ["applyVoiceWakePolicy", "policy applied"],
    agentVoiceWakeEnableButton: ["enableVoiceWake", "Hermes voice enabled"],
    agentVoiceWakeDisableButton: ["disableVoiceWake", "Hermes voice disabled"],
  };
  if (bridgeActions[id]) {
    event.preventDefault();
    const [methodName, statusLabel] = bridgeActions[id];
    callAndroidBridgeMethod(methodName, statusLabel);
    return;
  }
  if (id === "wakeWordCopyButton") {
    event.preventDefault();
    void copyTextLite(compactJson({ wake_word: state.wakeWordStatus, native: nativeShellInfo(), trace: bootTracePayload("wake_word_copy") }, 8000));
    return;
  }
  if (id === "wakeWordTrainButton") {
    event.preventDefault();
    state.wakeWordStatus = "training";
    renderWakeWordLite();
    mark("android_lite_wake_train_requested");
    return;
  }
  if (id === "agentAvatarButton") {
    event.preventDefault();
    setAgentOpen(el("agentOverlay")?.dataset.open !== "true");
    return;
  }
  if (id === "agentCloseButton") {
    event.preventDefault();
    setAgentOpen(false);
    return;
  }
  if (id === "agentPeopleButton") {
    event.preventDefault();
    const panel = el("agentPeoplePanel");
    if (panel) panel.hidden = !panel.hidden;
    return;
  }
  if (id === "agentSessionsButton") {
    event.preventDefault();
    const balloon = el("agentSessionsBalloon");
    if (balloon) balloon.hidden = !balloon.hidden;
    const list = el("agentSessionList");
    if (list && !list.childElementCount) list.replaceChildren(liteCard("Current", "local", "Android fast shell", "agent-session-item"));
    return;
  }
  if (id === "agentSettingsButton") {
    event.preventDefault();
    const balloon = el("agentSettingsBalloon");
    if (balloon) balloon.hidden = !balloon.hidden;
    return;
  }
  if (id === "agentNewSessionButton") {
    event.preventDefault();
    const messages = el("agentMessages");
    if (messages) messages.replaceChildren();
    appendAgentMessage("assistant", "New local chat.");
    return;
  }
  if (id === "agentTokenUsage") {
    event.preventDefault();
    const balloon = el("agentContextBalloon");
    if (balloon) balloon.hidden = !balloon.hidden;
    const diagnostics = el("agentDiagnostics");
    if (diagnostics) {
      diagnostics.replaceChildren(...definitionRows([
        ["Tokens", "local"],
        ["Turns", `${el("agentMessages")?.children?.length || 0}`],
        ["Context", Object.keys(state.appBootstrapPayload?.sections || {}).join(", ") || "shell"],
      ]).reduce((rows, node, index, source) => {
        if (index % 2 === 0) {
          const item = document.createElement("div");
          item.append(source[index], source[index + 1]);
          rows.push(item);
        }
        return rows;
      }, []));
    }
    return;
  }
  if (id === "agentAttachButton") {
    event.preventDefault();
    el("agentImageInput")?.click?.();
    return;
  }
}

function liteFastTapClickable(target) {
  return target?.closest?.("button,a,#googleSignInButton,#authGateGoogleSignInButton") || null;
}

function handleLitePointerDown(event) {
  if (event.button !== undefined && event.button !== 0) return;
  const clickable = liteFastTapClickable(event.target);
  liteFastTapStart = clickable ? {
    target: clickable,
    pointerId: event.pointerId ?? 0,
    pointerType: cleanText(event.pointerType || "touch", "touch"),
    x: Number(event.clientX || 0),
    y: Number(event.clientY || 0),
  } : null;
}

function handleLitePointerUp(event) {
  const start = liteFastTapStart;
  liteFastTapStart = null;
  if (!start) return;
  const pointerType = cleanText(event.pointerType || start.pointerType, "touch");
  if (pointerType === "mouse") return;
  if (start.pointerId && event.pointerId !== undefined && event.pointerId !== start.pointerId) return;
  const clickable = liteFastTapClickable(event.target);
  if (!clickable || clickable !== start.target) return;
  const dx = Number(event.clientX || 0) - start.x;
  const dy = Number(event.clientY || 0) - start.y;
  if (Math.hypot(dx, dy) > LITE_FAST_TAP_MOVE_PX) return;
  if (clickable.disabled || clickable.getAttribute?.("aria-disabled") === "true") return;
  event.preventDefault();
  event.stopPropagation();
  liteFastTapUntilMs = performance.now() + 450;
  const replay = new MouseEvent("click", { bubbles: true, cancelable: true, view: window });
  Object.defineProperty(replay, "__wasmAgentLiteFastTapReplay", { value: true });
  clickable.dispatchEvent(replay);
}

function handleLiteKeydown(event) {
  if (event.key === "Escape") {
    if (state.openModal) {
      event.preventDefault();
      closeLiteModal();
      return;
    }
    if (state.loginOpen) {
      event.preventDefault();
      setLoginOpen(false);
      return;
    }
  }
  if (event.key === "Enter" && event.target?.id === "joinSpaceInput") {
    event.preventDefault();
    void joinSpaceLite();
  }
}

function handleLiteSubmit(event) {
  if (event.target?.id === "agentForm") {
    submitLiteAgentMessage(event);
    return;
  }
  if (event.target?.id === "agentPeopleSearchForm") {
    event.preventDefault();
    appendAgentMessage("assistant", "People state is available after account bootstrap.");
    mark("android_lite_people_search_submitted");
  }
}

function installLiteInteractions() {
  if (state.liteInteractionsInstalled) return;
  state.liteInteractionsInstalled = true;
  readLiteSpaces();
  renderLiteSpaceLauncher();
  syncLiteAgentBounds();
  [
    ["pointerdown", handleLitePointerDown, { capture: true, passive: true }],
    ["pointerup", handleLitePointerUp, { capture: true, passive: false }],
  ].forEach(([type, handler, options]) => {
    document.addEventListener(type, handler, options);
    noteArchitectureListener("document", type, "lite_interactions");
  });
  document.addEventListener("click", handleLiteClick);
  noteArchitectureListener("document", "click", "lite_interactions");
  document.addEventListener("keydown", handleLiteKeydown);
  noteArchitectureListener("document", "keydown", "lite_interactions");
  document.addEventListener("submit", handleLiteSubmit, { capture: true });
  noteArchitectureListener("document", "submit", "lite_interactions");
  window.addEventListener("resize", syncLiteAgentBounds, { passive: true });
  noteArchitectureListener("window", "resize", "lite_interactions");
  ["resize", "scroll"].forEach((type) => {
    window.visualViewport?.addEventListener(type, syncLiteAgentBounds, { passive: true });
    if (window.visualViewport) noteArchitectureListener("visualViewport", type, "lite_interactions");
  });
  mark("android_lite_interactions_installed", {
    architecture: architectureSnapshot(),
    visible_controls: visibleControls(20).map((item) => item.id || item.aria_label || item.text).filter(Boolean),
  });
}

async function markPrepaintShell() {
  const prepaint = window.__WASM_AGENT_PREPAINT_SHELL;
  const cachedUser = readCached(AUTH_USER_STORAGE_KEY)?.user || prepaint?.user || null;
  const cachedConfig = readCached(CONFIG_STORAGE_KEY)?.config || null;
  if (cachedConfig) {
    state.config = cachedConfig;
    state.configChecked = true;
    mark("cached_config_applied", {
      reason: "android_lite",
      has_google_client_id: Boolean(cachedConfig?.auth?.googleClientId),
    });
  }
  if (cachedUser) {
    state.authUser = cachedUser;
    state.authChecked = false;
    if (app) {
      app.dataset.auth = "ready";
      app.dataset.status = "ready";
      app.dataset.panel = "home";
      app.dataset.androidApp = "lite";
      app.dataset.androidPrepaint = "authenticated";
      app.classList.add("android-prepaint-authenticated");
    }
    decorateAccount(cachedUser);
  }
  const shell = await Promise.resolve(window.__WASM_AGENT_PREPAINT_SHELL_AFTER_PAINT__ || prepaint || null).catch(() => prepaint || null);
  const visibleAtMs = Number(shell?.visibleAtMs || prepaint?.visibleAtMs || 0);
  const afterPaintAtMs = Number(shell?.afterPaintAtMs || prepaint?.afterPaintAtMs || visibleAtMs || performance.now());
  const markData = {
    pre_module: Boolean(prepaint),
    after_paint: true,
    pre_module_visible_at_ms: Math.round(visibleAtMs || 0),
    pre_module_after_paint_at_ms: Math.round(afterPaintAtMs || 0),
    pre_module_decorated_at_ms: Math.round(Number(shell?.decoratedAtMs || prepaint?.decoratedAtMs || 0)),
    config_cached: Boolean(cachedConfig?.auth?.googleClientId || shell?.configCached),
    email_present: Boolean(cachedUser?.email),
    user_id: cleanText(cachedUser?.id, ""),
    route: cleanText(shell?.route || route(), ""),
  };
  if (visibleAtMs) markAt("pre_module_cached_authenticated_shell_visible", visibleAtMs, markData);
  state.shellVisibleAtMs = afterPaintAtMs || performance.now();
  markAt("cached_authenticated_shell_visible", state.shellVisibleAtMs, markData);
  mark("main_finished", { authenticated: Boolean(state.authUser), cached_shell_rendered: Boolean(cachedUser), android_lite: true });
}

async function waitForInputQuiet(ms = FIRST_INPUT_QUIET_MS, maxWaitMs = 12000) {
  const started = Date.now();
  while (!document.hidden && (recentInput(ms) || inputPending()) && Date.now() - started < maxWaitMs) {
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
}

async function waitForFirstShellQuiet(reason = "startup", quietMs = FIRST_INPUT_QUIET_MS) {
  if (state.shellVisibleAtMs > 0) {
    const remaining = quietMs - Math.max(0, performance.now() - state.shellVisibleAtMs);
    if (remaining > 0) await new Promise((resolve) => setTimeout(resolve, remaining));
  }
  await waitForInputQuiet(quietMs);
  mark("android_first_shell_quiet_window", { reason, quiet_ms: Math.round(quietMs) });
}

async function fetchJson(url, options = {}) {
  const startedAt = performance.now();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), Number(options.timeoutMs || BOOTSTRAP_TIMEOUT_MS));
  try {
    const response = await fetch(url, {
      method: options.method || "GET",
      credentials: "include",
      cache: "no-store",
      headers: {
        "Accept": "application/json",
        ...(options.body ? { "Content-Type": "application/json" } : {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
      signal: controller.signal,
    });
    const contentType = response.headers.get("content-type") || "";
    const text = await response.text();
    const entry = {
      url,
      started_at_ms: Math.round(startedAt - bootTrace.startedAtMs),
      duration_ms: Math.round(performance.now() - startedAt),
      status: response.status,
      ok: response.ok,
      content_type: contentType,
    };
    noteArchitectureFetch(url, entry);
    bootTrace.fetches.push(redact(entry));
    while (bootTrace.fetches.length > BOOT_TRACE_LIMIT) bootTrace.fetches.shift();
    if (!contentType.includes("application/json")) throw new Error(`${url} returned ${contentType || "unknown content-type"}`);
    const payload = JSON.parse(text);
    if (!response.ok || payload?.ok === false) throw new Error(payload?.error?.message || `${url} failed ${response.status}`);
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

function applyBootstrapPayload(payload = {}) {
  const sections = payload.sections && typeof payload.sections === "object" ? payload.sections : {};
  const config = payload.config || sections.config || null;
  if (config) {
    state.config = config;
    state.configChecked = true;
    try {
      localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify({ config, cached_at: new Date().toISOString() }));
    } catch {
      // Config cache is best effort.
    }
  }
  const session = payload.session && typeof payload.session === "object" ? payload.session : null;
  state.authUser = payload.user || session?.user || state.authUser || null;
  state.authChecked = Boolean(session);
  if (state.authUser) writeCachedAuthUser(state.authUser);
  if (app) {
    app.dataset.auth = state.authUser ? "ready" : "locked";
    app.dataset.status = "ready";
    app.dataset.panel = "home";
    app.dataset.androidBootstrap = "reconciled";
  }
  decorateAccount(state.authUser);
  state.appBootstrapPayload = payload;
  window.__WASM_AGENT_ANDROID_BOOTSTRAP_PAYLOAD__ = payload;
  readLiteSpaces();
  renderLiteSpaceLauncher();
  renderActiveLiteModal();
}

async function hydrateFromBootstrap() {
  const startedAt = performance.now();
  mark("authenticated_hydration_started");
  await waitForFirstShellQuiet("bootstrap_fetch", 900);
  mark("app_bootstrap_fetch_started", { reason: "authenticated_hydration" });
  const payload = await fetchJson("/app/bootstrap", { timeoutMs: BOOTSTRAP_TIMEOUT_MS });
  applyBootstrapPayload(payload);
  mark("app_bootstrap_fetch_finished", {
    reason: "authenticated_hydration",
    elapsed_ms: Math.round(performance.now() - startedAt),
    authenticated: Boolean(state.authUser),
    section_count: Object.keys(payload.sections || {}).length,
    error_count: Object.keys(payload.errors || {}).length,
  });
  await waitForInputQuiet(250, 2000);
  mark("app_bootstrap_reconcile_render_started", { authenticated: Boolean(state.authUser) });
  app?.classList.add("android-lite-reconciled");
  mark("app_bootstrap_reconcile_render_finished", { authenticated: Boolean(state.authUser) });
  mark("authenticated_hydration_finished", {
    elapsed_ms: Math.round(performance.now() - startedAt),
    bootstrap: true,
    section_count: Object.keys(payload.sections || {}).length,
    error_count: Object.keys(payload.errors || {}).length,
  });
  notifyNativeReady("authenticated-app-hydrated");
  scheduleTraceUpload("authenticated_hydration_finished");
}

function runtimeSnapshot(options = {}) {
  return {
    schema: "hermes.wasm_agent.android_runtime_snapshot.v1",
    captured_at: new Date().toISOString(),
    route: route(),
    active_panel: "home",
    auth_state: state.authUser ? "authenticated" : state.authChecked ? "locked" : "checking",
    document_hidden: Boolean(document.hidden),
    recent_user_input_ms: androidLastInputAt ? Date.now() - androidLastInputAt : null,
    input_pending: inputPending(),
    open_modals: state.openModal ? [state.openModal] : [],
    native_bridge: {
      available: Boolean(window.wasmAgentAndroid),
      build_id: nativeShellInfo().buildId,
      install_device_hash: nativeShellInfo().installDeviceHash,
    },
    viewport: {
      width: Math.round(window.innerWidth || 0),
      height: Math.round(window.innerHeight || 0),
      device_pixel_ratio: Number(window.devicePixelRatio || 1),
    },
    visible_controls: visibleControls(Number(options.maxControls || 30)),
    recent_events: [],
    interaction_trace: bootTrace.inputs.slice(-8),
    architecture: architectureSnapshot(),
    capabilities: capabilities(),
    android_lite_boot: true,
    runtime_mode: "debug-lite",
    debug_shell: true,
    lite_interactions_installed: Boolean(state.liteInteractionsInstalled),
    bootstrap_sections: Object.keys(state.appBootstrapPayload?.sections || {}),
  };
}

function eventPointForElement(element) {
  const rect = element?.getBoundingClientRect?.();
  if (!rect) return { clientX: Math.max(1, Math.round(window.innerWidth / 2)), clientY: Math.max(1, Math.round(window.innerHeight / 2)) };
  return {
    clientX: Math.max(1, Math.round(rect.left + Math.min(rect.width - 1, Math.max(1, rect.width / 2)))),
    clientY: Math.max(1, Math.round(rect.top + Math.min(rect.height - 1, Math.max(1, rect.height / 2)))),
  };
}

function createProbeEvent(type, point) {
  const options = {
    bubbles: true,
    cancelable: true,
    composed: true,
    button: 0,
    buttons: type === "pointerup" || type === "mouseup" || type === "click" ? 0 : 1,
    clientX: point.clientX,
    clientY: point.clientY,
  };
  const event = type.startsWith("pointer") && typeof PointerEvent === "function"
    ? new PointerEvent(type, { ...options, pointerId: 1, pointerType: "touch", isPrimary: true, width: 1, height: 1, pressure: type === "pointerup" ? 0 : 0.5 })
    : new MouseEvent(type.replace(/^pointer/, "mouse"), options);
  try {
    Object.defineProperty(event, "__wasmAgentProbeCreatedAtMs", { value: performance.now(), configurable: true });
  } catch {
    event.__wasmAgentProbeCreatedAtMs = performance.now();
  }
  return event;
}

async function probeInputLatency(payload = {}) {
  const target = app || document.body || document.documentElement;
  const point = eventPointForElement(target);
  const types = (Array.isArray(payload.events) && payload.events.length ? payload.events : ["pointerdown", "pointerup", "click"])
    .map((item) => cleanText(item, "").toLowerCase())
    .filter((item) => ["pointerdown", "pointerup", "click", "mousedown", "mouseup"].includes(item))
    .slice(0, 5);
  const events = [];
  const startedAt = performance.now();
  const capture = (event) => {
    const probeCreatedAtMs = Number(event.__wasmAgentProbeCreatedAtMs || 0);
    const reference = probeCreatedAtMs > 0 ? probeCreatedAtMs : Number(event.timeStamp || performance.now());
    events.push({
      type: cleanText(event.type, ""),
      at_ms: elapsedMs(),
      event_time_ms: Math.round(event.timeStamp || 0),
      dispatch_delay_ms: Math.max(0, Math.round(performance.now() - reference)),
      dispatch_delay_source: probeCreatedAtMs > 0 ? "probe_created_at" : "event_timeStamp",
      handler_elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
      is_trusted: Boolean(event.isTrusted),
      target: describeTarget(event.target),
    });
  };
  types.forEach((type) => window.addEventListener(type.replace(/^pointer/, "pointer"), capture, { capture: true, passive: true }));
  try {
    await new Promise((resolve) => setTimeout(resolve, Number(payload.beforeDispatchMs || 0)));
    for (const type of types) {
      target.dispatchEvent(createProbeEvent(type, point));
      await new Promise((resolve) => setTimeout(resolve, Number(payload.stepDelayMs || 0)));
    }
    await new Promise((resolve) => window.requestAnimationFrame?.(() => resolve()) || setTimeout(resolve, 0));
  } finally {
    types.forEach((type) => window.removeEventListener(type.replace(/^pointer/, "pointer"), capture, { capture: true }));
  }
  const maxDispatchDelay = events.reduce((max, item) => Math.max(max, Number(item.dispatch_delay_ms || 0)), 0);
  const result = {
    ok: true,
    command: "probe_input_latency",
    synthetic: true,
    note: "Synthetic DOM dispatch probe; real touch proof still requires native/ADB tap evidence.",
    target: describeTarget(target),
    point,
    events,
    event_count: events.length,
    max_dispatch_delay_ms: maxDispatchDelay,
    elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
    active_panel: "home",
    app_auth: cleanText(app?.dataset?.auth, ""),
    app_status: cleanText(app?.dataset?.status, ""),
  };
  mark("android_input_latency_probe_finished", result);
  scheduleTraceUpload("android_input_latency_probe_finished");
  return result;
}

function litePanelAvailable(panel = "") {
  const clean = cleanText(panel, "");
  if (!clean) return false;
  if (clean === "home") return true;
  return allLiteSpaces().some((space) => space.id === clean);
}

function liteSpaceSwitchTargets(payload = {}) {
  const current = cleanText(state.activePanel, "home");
  const requested = cleanText(payload.targetPanel || payload.panel || "", "");
  const spaces = allLiteSpaces();
  let target = requested && litePanelAvailable(requested) ? requested : "";
  if (!target) target = spaces.find((space) => space.id !== current)?.id || "";
  if (!target && current !== "home") target = "home";
  if (!target) {
    createLiteSpace();
    target = state.selectedLiteSpaceId || current;
  }
  const back = cleanText(payload.returnPanel || "", "");
  return {
    current,
    target: target || current,
    returnPanel: back && litePanelAvailable(back) ? back : current,
  };
}

function setLitePanel(panel = "home") {
  const clean = cleanText(panel, "home");
  if (clean === "home") {
    state.selectedLiteSpaceId = "";
    state.activePanel = "home";
    if (app) {
      app.dataset.panel = "home";
      app.dataset.panelKind = "home";
    }
    setText("spaceLabel", "space-home");
    renderLiteSpaceLauncher();
    closeLiteModal();
    mark("android_lite_home_selected", { source: "native_control" });
    return true;
  }
  const space = allLiteSpaces().find((item) => item.id === clean);
  if (!space) return false;
  selectLiteSpace(space.id);
  return true;
}

async function probeSpaceSwitchLatency(payload = {}) {
  const targets = liteSpaceSwitchTargets(payload);
  const samples = [];
  const measure = async (phase, panel) => {
    const started = performance.now();
    const ok = setLitePanel(panel);
    const syncMs = Math.max(0, Math.round(performance.now() - started));
    await new Promise((resolve) => window.requestAnimationFrame?.(() => resolve()) || setTimeout(resolve, 0));
    const firstFrameMs = Math.max(0, Math.round(performance.now() - started));
    const settleMs = Math.max(0, Math.min(1000, Number(payload.settleMs || 96) || 0));
    if (settleMs) await new Promise((resolve) => setTimeout(resolve, settleMs));
    samples.push({
      phase,
      panel: cleanText(panel, ""),
      ok,
      active_panel: cleanText(state.activePanel, "home"),
      selected_space_id: cleanText(state.selectedLiteSpaceId, ""),
      sync_ms: syncMs,
      first_visual_ms: firstFrameMs,
      elapsed_ms: Math.max(0, Math.round(performance.now() - started)),
    });
  };
  const startedAt = performance.now();
  await measure("switch", targets.target);
  const holdMs = Math.max(0, Math.min(1000, Number(payload.holdMs || 80) || 0));
  if (holdMs) await new Promise((resolve) => setTimeout(resolve, holdMs));
  if (payload.return !== false && targets.returnPanel !== targets.target) {
    await measure("return", targets.returnPanel);
  }
  const result = {
    ok: samples.every((item) => item.ok),
    command: "probe_space_switch_latency",
    targets,
    samples,
    elapsed_ms: Math.max(0, Math.round(performance.now() - startedAt)),
    active_panel: cleanText(state.activePanel, "home"),
    selected_space_id: cleanText(state.selectedLiteSpaceId, ""),
    architecture: architectureSnapshot(),
  };
  mark("android_space_switch_latency_probe_finished", result);
  scheduleTraceUpload("android_space_switch_latency_probe_finished");
  return result;
}

function bootMarkTime(phasePattern) {
  const pattern = phasePattern instanceof RegExp ? phasePattern : new RegExp(String(phasePattern || ""), "i");
  const entry = bootTrace.marks.find((item) => pattern.test(cleanText(item.phase, "")));
  return entry ? Number(entry.at_ms || 0) : null;
}

function androidNativeUxReport(reason = "snapshot") {
  const longTasks = bootTrace.longTasks || [];
  const maxLongTask = longTasks.reduce((max, item) => Math.max(max, Number(item.duration_ms || 0)), 0);
  return {
    schema: "hermes.wasm_agent.android_native_ux_report.v1",
    reason: cleanText(reason, ""),
    generated_at: new Date().toISOString(),
    report_path: "reports/android/responsiveness/<timestamp>-android-native-ux.json",
    source: "android-webview-debug-lite",
    activity_create_timestamp: null,
    first_webview_load_url_timestamp: null,
    first_navigation_start_timestamp: null,
    first_content_paint_marker_ms: bootMarkTime(/prepaint|shell_visible|main_finished/),
    first_interactive_marker_ms: bootMarkTime(/input_latency_probe_installed|lite_interactions_installed|authenticated_hydration_finished/),
    full_ui_ready_marker_ms: bootMarkTime(/authenticated_hydration_finished|main_finished/),
    backend_config_health_probe: {
      result: queryParam("healthProbes", "afterFirstPaint"),
      blocks_first_load: false,
    },
    wake_service_start_timestamp: null,
    wake_model_asr_init: {
      diagnostics_deferred: true,
      wake_disabled_by_query: perfSafeMode() || queryParam("wake", "").toLowerCase() === "off",
    },
    bridge_call_count_during_boot: 0,
    console_messages_forwarded_during_boot: 0,
    diagnostics_writes_during_boot: 0,
    long_tasks_count: longTasks.length,
    long_tasks_max_duration_ms: maxLongTask,
    frame_gap_p50_ms: 0,
    frame_gap_p95_ms: 0,
    frame_gap_max_ms: 0,
    touch_event_count: bootTrace.inputs.length,
    ignored_touch_count: 0,
    ignored_touch_reasons: {},
    minimap_requested_count: 0,
    minimap_executed_count: 0,
    minimap_skipped_count: 0,
    canvas_pan_start_count: 0,
    canvas_pan_move_count: 0,
    canvas_pan_end_count: 0,
    app_responsiveness_verdict: maxLongTask >= 2000 ? "red" : maxLongTask >= 120 ? "yellow" : "green",
    architecture: architectureSnapshot(),
    boot_flags: {
      perfSafeMode: perfSafeMode(),
      wake: perfSafeMode() ? "off" : queryParam("wake", "deferred"),
      bridgeDiagnostics: perfSafeMode() ? "off" : queryParam("bridgeDiagnostics", "sampled"),
      healthProbes: queryParam("healthProbes", "afterFirstPaint"),
    },
  };
}

function bootTracePayload(reason = "snapshot") {
  const nav = performance.getEntriesByType?.("navigation")?.[0];
  const resources = (performance.getEntriesByType?.("resource") || [])
    .map((entry) => ({
      name: clipped(entry.name, 260),
      initiator_type: clipped(entry.initiatorType, 80),
      start_ms: Math.round(entry.startTime || 0),
      duration_ms: Math.round(entry.duration || 0),
      transfer_size: Math.round(entry.transferSize || 0),
      encoded_body_size: Math.round(entry.encodedBodySize || 0),
    }))
    .sort((a, b) => b.duration_ms - a.duration_ms)
    .slice(0, BOOT_TRACE_SLOW_RESOURCE_LIMIT);
  return {
    schema: bootTrace.schema,
    reason,
    boot_id: bootTrace.bootId,
    started_at: bootTrace.startedAt,
    elapsed_ms: elapsedMs(),
    href: window.location.href,
    user_agent: navigator.userAgent || "",
    build_id: nativeShellInfo().buildId || "android-lite",
    native_shell: nativeShellInfo(),
    app: {
      auth_checked: Boolean(state.authChecked),
      config_checked: Boolean(state.configChecked),
      authenticated: Boolean(state.authUser),
      active_panel: "home",
      app_status: cleanText(app?.dataset?.status, ""),
      app_auth: cleanText(app?.dataset?.auth, ""),
      last_error: "",
      auth_session_load_phase: state.authUser ? "authenticated" : "anonymous",
      load_auth_session_reached: false,
      native_app_ready_notified: Boolean(state.nativeAppReadyNotified),
      android_lite_boot: true,
    },
    navigation: nav ? {
      start_ms: Math.round(nav.startTime || 0),
      duration_ms: Math.round(nav.duration || 0),
      dom_interactive_ms: Math.round(nav.domInteractive || 0),
      dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd || 0),
      load_event_ms: Math.round(nav.loadEventEnd || 0),
      transfer_size: Math.round(nav.transferSize || 0),
    } : null,
    marks: bootTrace.marks.slice(-BOOT_TRACE_LIMIT),
    fetches: bootTrace.fetches.slice(-BOOT_TRACE_LIMIT),
    inputs: bootTrace.inputs.slice(-BOOT_TRACE_INPUT_LIMIT),
    long_tasks: bootTrace.longTasks.slice(-BOOT_TRACE_LONG_TASK_LIMIT),
    errors: bootTrace.errors.slice(-40),
    slow_resources: resources,
    architecture: architectureSnapshot(),
    android_native_ux_report: androidNativeUxReport(reason),
  };
}

try {
  window.__wasmAgentAndroidNativeUxReport = (reason = "manual") => androidNativeUxReport(reason);
} catch {
  // Report exposure is best effort.
}

async function uploadTrace(reason = "snapshot", options = {}) {
  if (!options.immediate) {
    await waitForInputQuiet(500, 4000);
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
  const body = JSON.stringify({
    schema: "hermes.wasm_agent.client_boot_trace_upload.v1",
    device_id: deviceId(),
    build_id: nativeShellInfo().buildId || "android-lite",
    reason,
    boot_trace: bootTracePayload(reason),
  });
  try {
    await fetch("/native/diagnostics", {
      method: "POST",
      cache: "no-store",
      keepalive: Boolean(options.keepalive),
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
      },
      body,
    });
  } catch {
    // Boot tracing must never affect the app.
  }
}

function scheduleTraceUpload(reason = "snapshot") {
  if (traceUploadTimer) clearTimeout(traceUploadTimer);
  traceUploadTimer = setTimeout(() => {
    traceUploadTimer = 0;
    void uploadTrace(reason);
  }, TRACE_UPLOAD_DEBOUNCE_MS);
}

function notifyNativeReady(reason = "android-lite-ready") {
  state.nativeAppReadyNotified = true;
  try {
    window.wasmAgentAndroid?.appReady?.(JSON.stringify({ reason, route: route(), authenticated: Boolean(state.authUser) }));
  } catch {
    // Native ready notification is best effort.
  }
}

function textEncoder() {
  if (!textEncoder.instance) textEncoder.instance = new TextEncoder();
  return textEncoder.instance;
}

function textDecoder() {
  if (!textDecoder.instance) textDecoder.instance = new TextDecoder();
  return textDecoder.instance;
}

function utf8(value) {
  return textEncoder().encode(String(value ?? ""));
}

function jsonBytes(value) {
  return utf8(JSON.stringify(value ?? null));
}

function concatBytes(chunks = []) {
  const total = chunks.reduce((sum, chunk) => sum + chunk.byteLength, 0);
  const output = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    output.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return output;
}

function encodeValue(value) {
  if (value === null || typeof value === "undefined") return { type: WAO_TLV_NULL, payload: new Uint8Array() };
  if (typeof value === "boolean") return { type: WAO_TLV_BOOL, payload: Uint8Array.of(value ? 1 : 0) };
  if (Number.isInteger(value)) {
    const payload = new Uint8Array(8);
    new DataView(payload.buffer).setBigInt64(0, BigInt(value), true);
    return { type: WAO_TLV_I64, payload };
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    const payload = new Uint8Array(8);
    new DataView(payload.buffer).setFloat64(0, value, true);
    return { type: WAO_TLV_F64, payload };
  }
  if (value instanceof ArrayBuffer) return { type: WAO_TLV_BYTES, payload: new Uint8Array(value) };
  if (ArrayBuffer.isView(value)) return { type: WAO_TLV_BYTES, payload: new Uint8Array(value.buffer, value.byteOffset, value.byteLength) };
  if (typeof value === "object") return { type: WAO_TLV_JSON, payload: jsonBytes(value) };
  return { type: WAO_TLV_UTF8, payload: utf8(value) };
}

function decodeValue(type, payload) {
  if (type === WAO_TLV_NULL) return null;
  if (type === WAO_TLV_BOOL) return Boolean(payload[0]);
  if (type === WAO_TLV_I64 && payload.byteLength === 8) {
    const value = new DataView(payload.buffer, payload.byteOffset, payload.byteLength).getBigInt64(0, true);
    return value <= BigInt(Number.MAX_SAFE_INTEGER) && value >= BigInt(Number.MIN_SAFE_INTEGER) ? Number(value) : value.toString();
  }
  if (type === WAO_TLV_F64 && payload.byteLength === 8) {
    return new DataView(payload.buffer, payload.byteOffset, payload.byteLength).getFloat64(0, true);
  }
  if (type === WAO_TLV_BYTES) return payload.slice().buffer;
  if (type === WAO_TLV_JSON) {
    try {
      return JSON.parse(textDecoder().decode(payload));
    } catch {
      return {};
    }
  }
  if (type === WAO_TLV_UTF8) return textDecoder().decode(payload);
  return payload.slice().buffer;
}

function encodeTlv(fields = {}) {
  const chunks = [];
  for (const [name, value] of Object.entries(fields || {})) {
    const fieldId = WAO_FIELD_IDS[name];
    if (!fieldId) continue;
    const encoded = encodeValue(value);
    const header = new Uint8Array(WAO_TLV_HEADER_BYTES);
    const view = new DataView(header.buffer);
    view.setUint16(0, fieldId, true);
    view.setUint8(2, encoded.type);
    view.setUint8(3, 0);
    view.setUint32(4, encoded.payload.byteLength, true);
    chunks.push(header, encoded.payload);
  }
  return concatBytes(chunks);
}

function decodeTlv(payload) {
  const bytes = payload instanceof Uint8Array ? payload : new Uint8Array(payload || 0);
  const fields = {};
  let offset = 0;
  while (offset + WAO_TLV_HEADER_BYTES <= bytes.byteLength) {
    const view = new DataView(bytes.buffer, bytes.byteOffset + offset, WAO_TLV_HEADER_BYTES);
    const fieldId = view.getUint16(0, true);
    const type = view.getUint8(2);
    const length = view.getUint32(4, true);
    offset += WAO_TLV_HEADER_BYTES;
    if (offset + length > bytes.byteLength) break;
    fields[WAO_FIELD_NAMES[fieldId] || `field_${fieldId}`] = decodeValue(type, bytes.subarray(offset, offset + length));
    offset += length;
  }
  return fields;
}

function encodeFrame(typeName, fields = {}, options = {}) {
  const body = encodeTlv(fields);
  const output = new Uint8Array(WAO_HEADER_BYTES + body.byteLength);
  output[0] = 87;
  output[1] = 65;
  output[2] = 79;
  output[3] = 49;
  const view = new DataView(output.buffer);
  view.setUint8(4, WAO_VERSION);
  view.setUint8(5, WAO_FRAME_TYPES[String(typeName || "EVENT").toUpperCase()] || WAO_FRAME_TYPES.EVENT);
  view.setUint16(6, Number(options.schemaId || 0), true);
  view.setUint32(8, Number(options.flags || 0), true);
  view.setUint32(12, Number(options.session || 0), true);
  view.setBigUint64(16, BigInt(options.seq || nativeObsSeq++), true);
  view.setBigUint64(24, BigInt(options.ack || 0), true);
  view.setBigUint64(32, BigInt(Math.max(0, Math.round(performance.now()))), true);
  output.set(body, WAO_HEADER_BYTES);
  return output.buffer;
}

function decodeFrame(data) {
  const bytes = data instanceof ArrayBuffer ? new Uint8Array(data) : new Uint8Array(data.buffer || data);
  if (bytes.byteLength < WAO_HEADER_BYTES || bytes[0] !== 87 || bytes[1] !== 65 || bytes[2] !== 79 || bytes[3] !== 49) throw new Error("bad_wao_frame");
  const view = new DataView(bytes.buffer, bytes.byteOffset, WAO_HEADER_BYTES);
  const typeId = view.getUint8(5);
  const seq = view.getBigUint64(16, true);
  return {
    type: WAO_FRAME_TYPE_NAMES[typeId] || `UNKNOWN_${typeId}`,
    seq: seq <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(seq) : seq.toString(),
    fields: decodeTlv(bytes.subarray(WAO_HEADER_BYTES)),
  };
}

function nativeObsSend(typeName, fields = {}, options = {}) {
  if (!nativeObsSocket || nativeObsSocket.readyState !== WebSocket.OPEN) return false;
  try {
    nativeObsSocket.send(encodeFrame(typeName, fields, options));
    return true;
  } catch {
    return false;
  }
}

async function executeCommand(command = {}) {
  const type = cleanText(command.type || command.command || "");
  const payload = command.payload && typeof command.payload === "object" ? command.payload : {};
  if (type === "get_runtime_snapshot" || type === "status") {
    await waitForInputQuiet(250, 1500);
    return { ok: true, command: type, snapshot: runtimeSnapshot(payload) };
  }
  if (type === "get_android_native_ux_report") {
    await waitForInputQuiet(250, 1500);
    return { ok: true, command: type, report: androidNativeUxReport("native_control") };
  }
  if (type === "probe_input_latency") return probeInputLatency(payload);
  if (type === "probe_space_switch_latency") return probeSpaceSwitchLatency(payload);
  if (type === "upload_diagnostics") {
    await uploadTrace("native_control_upload_diagnostics", { immediate: payload.immediate === true });
    return { ok: true, command: type, uploaded: true };
  }
  if (type === "reload") {
    const bridge = nativeReloadBridge();
    const nativeReloadAvailable = Boolean(bridge);
    const currentBootId = bootTrace.bootId;
    window.setTimeout(() => {
      try {
        bridge?.reload?.();
      } catch {
        // Browser fallback below keeps reload command falsifiable.
      }
      window.setTimeout(() => {
        try {
          if (window.__wasmAgentBootTrace?.("reload_fallback_check")?.boot_id === currentBootId) {
            window.location.reload();
          }
        } catch {
          window.location.reload();
        }
      }, 350);
    }, 80);
    return {
      ok: true,
      command: type,
      reloading: true,
      native_reload_available: nativeReloadAvailable,
      browser_reload_fallback_ms: 430,
    };
  }
  return { ok: false, command: type, error: "unsupported_android_lite_command" };
}

async function handleCommand(fields = {}, frame = {}) {
  const command = {
    id: cleanText(fields.command_id, ""),
    type: cleanText(fields.op || fields.type, ""),
    payload: fields.payload_json && typeof fields.payload_json === "object" ? fields.payload_json : {},
  };
  if (!command.id) return;
  nativeObsSend("COMMAND_ACK", {
    device_id: deviceId(),
    command_id: command.id,
    op: command.type,
    status: "accepted",
    ts_ms: Date.now(),
  }, { ack: frame.seq || 0 });
  const started = performance.now();
  let result;
  try {
    result = await executeCommand(command);
  } catch (error) {
    result = { ok: false, command: command.type, error: cleanText(error?.message || error, "command failed") };
  }
  nativeObsSend("COMMAND_ACK", {
    device_id: deviceId(),
    command_id: command.id,
    op: command.type,
    status: "finished",
    latency_ms: Math.max(0, Math.round(performance.now() - started)),
    result_json: {
      ...result,
      reason: "wao",
      executedAt: new Date().toISOString(),
      capabilities: capabilities(),
    },
  }, { ack: frame.seq || 0 });
}

function connectNativeObservability() {
  if (typeof WebSocket !== "function" || nativeObsSocket) return;
  const url = new URL("/native/obs/v1", window.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.searchParams.set("device_id", deviceId());
  url.searchParams.set("role", "android-webview");
  url.searchParams.set("topics", "commands,performance");
  try {
    nativeObsSocket = new WebSocket(url.toString());
    nativeObsSocket.binaryType = "arraybuffer";
  } catch {
    nativeObsSocket = null;
    return;
  }
  nativeObsSocket.addEventListener("open", () => {
    mark("native_observability_socket_open");
    nativeObsSend("HELLO", {
      device_id: deviceId(),
      role: "android-webview",
      topics: ["commands", "performance"],
      build_id: nativeShellInfo().buildId,
      route: route(),
      runtime: "android-webview-lite",
      payload_json: capabilities(),
    });
    if (nativeObsHeartbeatTimer) clearInterval(nativeObsHeartbeatTimer);
    nativeObsHeartbeatTimer = setInterval(() => {
      nativeObsSend("HEARTBEAT", {
        device_id: deviceId(),
        build_id: nativeShellInfo().buildId,
        route: route(),
        runtime: "android-webview-lite",
        ts_ms: Date.now(),
      });
    }, NATIVE_OBS_HEARTBEAT_MS);
  });
  nativeObsSocket.addEventListener("message", (event) => {
    try {
      const frame = typeof event.data === "string" ? { type: "EVENT", fields: JSON.parse(event.data) } : decodeFrame(event.data);
      if (frame.type === "COMMAND") void handleCommand(frame.fields || {}, frame);
    } catch (error) {
      bootTrace.errors.push({ at_ms: elapsedMs(), message: cleanText(error?.message || error, "wao decode failed") });
    }
  });
  nativeObsSocket.addEventListener("close", () => {
    if (nativeObsHeartbeatTimer) clearInterval(nativeObsHeartbeatTimer);
    nativeObsHeartbeatTimer = 0;
    nativeObsSocket = null;
  });
}

async function main() {
  mark("fatal_trap_installed");
  installInputAndLongTaskProbe();
  mark("main_started", { ready_state: document.readyState, android_lite: true });
  await markPrepaintShell();
  installLiteInteractions();
  scheduleTraceUpload("cached_authenticated_shell_visible");
  notifyNativeReady("cached-authenticated-shell");
  connectNativeObservability();
  try {
    await hydrateFromBootstrap();
  } catch (error) {
    bootTrace.errors.push({ at_ms: elapsedMs(), message: cleanText(error?.message || error, "bootstrap failed") });
    mark("authenticated_hydration_bootstrap_error", { message: cleanText(error?.message || error, "bootstrap failed") });
    scheduleTraceUpload("authenticated_hydration_bootstrap_error");
  }
}

window.__wasmAgentBootTrace = (reason = "manual") => bootTracePayload(reason);
window.__wasmAgentAndroidLite = {
  capabilities,
  runtimeSnapshot,
  probeInputLatency,
  uploadTrace,
};

main().catch((error) => {
  bootTrace.errors.push({ at_ms: elapsedMs(), message: cleanText(error?.message || error, "android lite fatal") });
  mark("android_lite_fatal", { message: cleanText(error?.message || error, "android lite fatal") });
  void uploadTrace("android_lite_fatal", { immediate: true, keepalive: true });
});
