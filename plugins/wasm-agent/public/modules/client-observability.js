const SCHEMA = "hermes.wasm_agent.client_observability.v1";
const MIN_LEASE_MS = 5000;
const MAX_LEASE_MS = 120000;
const INTERACTION_OUTCOME_EVENT = "wasm-agent:interaction-outcome";
const INTERACTION_TRAIL_LIMIT = 24;

let expiresAt = 0;
let timer = 0;
let observer = null;
const counters = { long_tasks: 0, resources: 0, errors: 0, rejections: 0 };
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

globalThis.addEventListener?.(INTERACTION_OUTCOME_EVENT, (event) => appendInteractionOutcome(event.detail));
globalThis.addEventListener?.("error", () => { counters.errors += 1; });
globalThis.addEventListener?.("unhandledrejection", () => { counters.rejections += 1; });

function active() {
  return expiresAt > Date.now();
}

export function moduleReleaseStatus(value = globalThis.__WASM_AGENT_MODULE_RELEASE__) {
  const releaseId = String(value?.release_id || "");
  if (value?.schema !== "hermes.wasm_agent.module_release.v1" || !/^[a-f0-9]{64}$/.test(releaseId)) {
    return { release_id: null, entry: null };
  }
  return {
    release_id: releaseId,
    entry: String(value.entry || "").slice(0, 160) || null,
  };
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
  counters.errors = 0;
  counters.rejections = 0;
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
  const scripts = Array.from(doc?.scripts || []).slice(0, 80);
  const activeElement = doc?.activeElement;
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
      ready_state: String(doc?.readyState || "unknown"),
      active_control: activeElement ? {
        tag: String(activeElement.tagName || "").toLowerCase().slice(0, 20),
        role: String(activeElement.getAttribute?.("role") || "").slice(0, 40),
        disabled: activeElement.matches?.(":disabled") === true,
      } : null,
      modules: {
        scripts: scripts.length,
        module_scripts: scripts.filter((node) => node.type === "module").length,
        ...moduleReleaseStatus(),
      },
      viewport: { width: Math.round(globalThis.innerWidth || 0), height: Math.round(globalThis.innerHeight || 0), dpr: Number(globalThis.devicePixelRatio || 1) },
    },
    interaction_trail: interactionTrail.slice(-12).reverse(),
    proof: ["client.runtime.diagnostic_snapshot"],
  };
}

export async function executeClientObservability(type, payload) {
  if (type === "observability_enable") return enable(payload);
  if (type === "observability_collect") return collect();
  if (type === "runtime_diagnose") { enable(payload); return collect(); }
  if (type === "observability_disable") return disable();
  if (type === "observability_status") return status();
  return { ok: false, error: "unsupported_observability_command" };
}

export { appendInteractionOutcome, INTERACTION_TRAIL_LIMIT };

function nativeOperation(operation, payload) {
  const bridge = globalThis.wasmAgentNative;
  if (!bridge?.runDownloadedOperation) return null;
  return bridge.runDownloadedOperation(JSON.stringify({ operationId: operation }), JSON.stringify(payload || {}));
}
