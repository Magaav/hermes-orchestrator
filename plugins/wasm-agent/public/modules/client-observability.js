const SCHEMA = "hermes.wasm_agent.client_observability.v1";
const MIN_LEASE_MS = 5000;
const MAX_LEASE_MS = 120000;
const INTERACTION_OUTCOME_EVENT = "wasm-agent:interaction-outcome";
const INTERACTION_TRAIL_LIMIT = 24;
const INPUT_RECEIPT_SCHEMA = "hermes.wasm_agent.native_web_surface_input_receipt.v1";
const INPUT_RECEIPT_MAX_AGE_MS = 120000;
const INPUT_RECEIPT_SOURCES = new Set(["electron_synthetic", "unattributed_native_input"]);
const OPAQUE_COMMAND_ID = /^[a-zA-Z0-9._:-]{1,120}$/;

let expiresAt = 0;
let timer = 0;
let observer = null;
const counters = { long_tasks: 0, resources: 0 };
const interactionTrail = [];

function appendInteractionOutcome(value = {}) {
  const entry = {
    at: String(value.at || new Date().toISOString()).slice(0, 40),
    widget: String(value.widget || "").slice(0, 80),
    action: String(value.action || "").slice(0, 80),
    outcome: String(value.outcome || "").slice(0, 80),
    reason: String(value.reason || "").slice(0, 160),
  };
  interactionTrail.push(entry);
  if (interactionTrail.length > INTERACTION_TRAIL_LIMIT) interactionTrail.splice(0, interactionTrail.length - INTERACTION_TRAIL_LIMIT);
  return entry;
}

function safeNavigationTarget(value) {
  try {
    const url = new URL(String(value || ""), globalThis.location?.href);
    return `${url.origin}${url.pathname}`.slice(0, 500);
  } catch { return "invalid_url"; }
}

function normalizedInputReceipt(value, surfaceId) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const atMs = Date.parse(String(value.at || ""));
  const ageMs = value.age_ms;
  const observedAgeMs = Date.now() - atMs;
  const id = String(value.id || "").trim().slice(0, 80);
  const receiptSurfaceId = String(value.surface_id || "").trim().slice(0, 80);
  const inputSource = Object.prototype.hasOwnProperty.call(value, "input_source")
    ? value.input_source
    : "unattributed_native_input";
  const hasCommandId = Object.prototype.hasOwnProperty.call(value, "command_id");
  const commandId = hasCommandId ? value.command_id : null;
  if (
    value.schema !== INPUT_RECEIPT_SCHEMA
    || !/^[a-zA-Z0-9._:-]+$/.test(id)
    || receiptSurfaceId !== surfaceId
    || value.action !== "pointer.primary_gesture"
    || value.outcome !== "observed_pre_dispatch"
    || value.button !== "left"
    || value.redacted !== true
    || value.current_document !== true
    || !Number.isFinite(atMs)
    || typeof ageMs !== "number"
    || !Number.isFinite(ageMs)
    || ageMs < 0
    || ageMs >= INPUT_RECEIPT_MAX_AGE_MS
    || observedAgeMs < -5000
    || observedAgeMs >= INPUT_RECEIPT_MAX_AGE_MS
    || typeof inputSource !== "string"
    || !INPUT_RECEIPT_SOURCES.has(inputSource)
    || (hasCommandId && (
      inputSource !== "electron_synthetic"
      || typeof commandId !== "string"
      || !OPAQUE_COMMAND_ID.test(commandId)
    ))
  ) return null;

  const candidateX = value.x;
  const candidateY = value.y;
  const width = value.viewport?.width;
  const height = value.viewport?.height;
  if (!(
    typeof candidateX === "number" && typeof candidateY === "number"
    && typeof width === "number" && typeof height === "number"
    && Number.isFinite(candidateX) && Number.isFinite(candidateY)
    && Number.isFinite(width) && Number.isFinite(height)
    && Math.round(width) > 0 && Math.round(height) > 0
    && candidateX >= 0 && candidateY >= 0
    && Math.round(candidateX) < Math.round(width) && Math.round(candidateY) < Math.round(height)
  )) return null;
  const receipt = {
    schema: INPUT_RECEIPT_SCHEMA,
    id,
    surface_id: receiptSurfaceId,
    at: new Date(atMs).toISOString(),
    action: "pointer.primary_gesture",
    outcome: "observed_pre_dispatch",
    button: "left",
    x: Math.round(candidateX),
    y: Math.round(candidateY),
    viewport: { width: Math.round(width), height: Math.round(height) },
    current_document: true,
    age_ms: Math.round(ageMs),
    input_source: inputSource,
    redacted: true,
  };
  if (hasCommandId) receipt.command_id = commandId;
  return receipt;
}

globalThis.addEventListener?.(INTERACTION_OUTCOME_EVENT, (event) => appendInteractionOutcome(event.detail));
globalThis.document?.addEventListener?.("wasm-agent:browser-command", (event) => {
  const operation = String(event.detail?.operation || "");
  if (!operation.startsWith("browser.")) return;
  appendInteractionOutcome({
    widget: "browser",
    action: operation,
    outcome: operation.endsWith(".failed") ? "failed" : "acknowledged",
    reason: event.detail?.args?.error || (operation === "browser.navigate" ? safeNavigationTarget(event.detail?.args?.url) : ""),
  });
});

function active() {
  return expiresAt > Date.now();
}

function disable(reason = "operator") {
  clearTimeout(timer);
  timer = 0;
  observer?.disconnect();
  observer = null;
  expiresAt = 0;
  try { nativeOperation("observability_disable", {}); } catch {}
  return { ...status(), reason };
}

function status() {
  const enabled = active();
  return {
    ok: true,
    schema: SCHEMA,
    active: enabled,
    expires_at: enabled ? new Date(expiresAt).toISOString() : null,
    remaining_ms: enabled ? Math.max(0, expiresAt - Date.now()) : 0,
    cdp: globalThis.wasmAgentNative?.runDownloadedOperation
      ? { available: true, mode: "android_webview_devtools_socket", public_debug_port: false }
      : { available: false, mode: "external", required: "authorized_browser_cdp" },
    retention: "aggregate_counters_only",
    counters: { ...counters },
  };
}

function enable(payload = {}) {
  disable("renewed");
  const requested = Number(payload.lease_ms || payload.leaseMs || 30000);
  const leaseMs = Math.min(MAX_LEASE_MS, Math.max(MIN_LEASE_MS, Number.isFinite(requested) ? requested : 30000));
  counters.long_tasks = 0;
  counters.resources = 0;
  expiresAt = Date.now() + leaseMs;
  if (globalThis.PerformanceObserver) {
    observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.entryType === "longtask") counters.long_tasks += 1;
        if (entry.entryType === "resource") counters.resources += 1;
      }
    });
    for (const type of ["longtask", "resource"]) {
      try { observer.observe({ type, buffered: false }); } catch {}
    }
  }
  timer = setTimeout(() => disable("lease_expired"), leaseMs);
  try { nativeOperation("observability_enable", { lease_ms: leaseMs }); } catch {}
  return status();
}

function collect() {
  if (!active()) return { ok: false, error: "observability_lease_required", ...status() };
  const doc = globalThis.document;
  const nav = performance.getEntriesByType?.("navigation")?.[0];
  return {
    ...status(),
    analytics: {
      route: `${location.origin}${location.pathname}`,
      visibility: doc?.visibilityState || "unknown",
      nodes: doc?.getElementsByTagName?.("*")?.length || 0,
      buttons: doc?.querySelectorAll?.("button,[role='button']")?.length || 0,
      inputs: doc?.querySelectorAll?.("input,textarea,select")?.length || 0,
      widgets: doc?.querySelectorAll?.("[data-widget-id]")?.length || 0,
      navigation_ms: Number.isFinite(nav?.duration) ? Math.round(nav.duration) : null,
    },
  };
}

async function browserSurface() {
  const invoke = globalThis.wasmAgentNative?.webSurfaces?.invoke;
  if (typeof invoke !== "function") return { ok: false, error: "native_browser_unavailable", interaction_trail: interactionTrail.slice().reverse() };
  let surface;
  try { surface = await invoke("status", { id: "browser", includeInputReceipt: true }); }
  catch (error) {
    return { ok: false, error: String(error?.message || error).slice(0, 160), interaction_trail: interactionTrail.slice().reverse(), proof: ["client.interaction_outcome.trail"] };
  }
  const surfaceId = String(surface?.id || "browser").slice(0, 80);
  const inputReceiptState = surface?.inputReceiptEnabled === true
    ? "enabled"
    : (surface?.inputReceiptEnabled === false ? "disabled" : "unsupported");
  const inputReceipt = surfaceId === "browser" && inputReceiptState === "enabled"
    ? normalizedInputReceipt(surface?.inputReceipt, "browser")
    : null;
  const proof = ["native.web_surface.status", "client.interaction_outcome.trail"];
  if (inputReceipt) proof.push("native.web_surface.input_receipt");
  return {
    ok: true,
    schema: SCHEMA,
    browser: {
      id: surfaceId,
      status: String(surface?.status || "unknown"),
      visible: surface?.visible === true,
      url: String(surface?.url || "").slice(0, 2000),
      title: String(surface?.title || "").slice(0, 300),
      loading: surface?.loading === true,
      browser_identity: surface?.browserIdentity || null,
      input_receipt_state: inputReceiptState,
      input_receipt: inputReceipt,
      error: surface?.error || null,
    },
    interaction_trail: interactionTrail.slice().reverse(),
    proof,
  };
}

export async function executeClientObservability(type, payload) {
  if (type === "observability_enable") return enable(payload);
  if (type === "observability_collect") return collect();
  if (type === "observability_disable") return disable();
  if (type === "observability_status") return status();
  if (type === "observability_browser_surface") return browserSurface();
  return { ok: false, error: "unsupported_observability_command" };
}

export { appendInteractionOutcome, INTERACTION_TRAIL_LIMIT };

function nativeOperation(operation, payload) {
  const bridge = globalThis.wasmAgentNative;
  if (!bridge?.runDownloadedOperation) return null;
  return bridge.runDownloadedOperation(JSON.stringify({ operationId: operation }), JSON.stringify(payload || {}));
}
