"use strict";

const { supervisorStatus } = require("./supervisor-client");

const SCHEMA = "hermes.wasm_agent.observability_kernel.v1";
const DEFAULT_LEASE_MS = 30_000;
const MAX_LEASE_MS = 120_000;
const MAX_EVENTS = 200;

function boundedLeaseMs(value) {
  const requested = Number(value || DEFAULT_LEASE_MS);
  return Math.max(5_000, Math.min(Number.isFinite(requested) ? requested : DEFAULT_LEASE_MS, MAX_LEASE_MS));
}

function createObservabilityKernel({ now = () => Date.now(), setTimer = setTimeout, clearTimer = clearTimeout, supervisorSnapshot = supervisorStatus } = {}) {
  let active = null;
  let timer = null;
  const counters = { console: 0, exceptions: 0, failedRequests: 0, eventsDropped: 0 };

  function contentsFor(win) {
    return win && !win.isDestroyed?.() ? win.webContents : null;
  }

  function onMessage(_event, method, params = {}) {
    const count = counters.console + counters.exceptions + counters.failedRequests;
    if (count >= MAX_EVENTS) { counters.eventsDropped += 1; return; }
    if (method === "Runtime.consoleAPICalled" || method === "Log.entryAdded") counters.console += 1;
    if (method === "Runtime.exceptionThrown") counters.exceptions += 1;
    if (method === "Network.loadingFailed") counters.failedRequests += 1;
  }

  function status() {
    return {
      ok: true, schema: SCHEMA, active: Boolean(active), transport: "electron.webContents.debugger",
      expires_at: active ? new Date(active.expiresAt).toISOString() : "",
      remaining_ms: active ? Math.max(0, active.expiresAt - now()) : 0,
      counters: { ...counters }, retention: "counters-only", public_debug_port: false,
      native_update: supervisorSnapshot().updateTimeline || null,
    };
  }

  async function disable(reason = "requested") {
    if (timer) clearTimer(timer);
    timer = null;
    const current = active;
    active = null;
    if (current?.contents && !current.contents.isDestroyed?.()) {
      current.contents.debugger.removeListener("message", onMessage);
      if (current.contents.debugger.isAttached()) current.contents.debugger.detach();
    }
    return { ...status(), disabled: true, reason };
  }

  async function enable(win, payload = {}) {
    const contents = contentsFor(win);
    if (!contents) return { ok: false, schema: SCHEMA, error: "electron_web_contents_unavailable" };
    if (active?.contents !== contents) await disable("target_changed");
    const leaseMs = boundedLeaseMs(payload.lease_ms || payload.leaseMs);
    if (!contents.debugger.isAttached()) contents.debugger.attach("1.3");
    contents.debugger.removeListener("message", onMessage);
    contents.debugger.on("message", onMessage);
    for (const method of ["Runtime.enable", "Log.enable", "Network.enable", "Performance.enable"]) {
      await contents.debugger.sendCommand(method);
    }
    Object.keys(counters).forEach((key) => { counters[key] = 0; });
    active = { contents, expiresAt: now() + leaseMs };
    if (timer) clearTimer(timer);
    timer = setTimer(() => { void disable("lease_expired"); }, leaseMs);
    timer.unref?.();
    return { ...status(), enabled: true, lease_ms: leaseMs };
  }

  async function collect(payload = {}) {
    if (!active || active.expiresAt <= now()) return disable("lease_expired").then(() => ({ ok: false, schema: SCHEMA, error: "observability_lease_inactive" }));
    const contents = active.contents;
    const categories = new Set(Array.isArray(payload.categories) ? payload.categories : ["analytics", "performance"]);
    const result = { ...status(), collected_at: new Date(now()).toISOString() };
    if (categories.has("performance")) {
      const metrics = await contents.debugger.sendCommand("Performance.getMetrics");
      const keep = new Set(["Timestamp", "Documents", "Frames", "Nodes", "LayoutCount", "RecalcStyleCount", "ScriptDuration", "TaskDuration", "JSHeapUsedSize"]);
      result.performance = Object.fromEntries((metrics.metrics || []).filter((item) => keep.has(item.name)).map((item) => [item.name, item.value]));
    }
    if (categories.has("analytics") || categories.has("dom")) {
      const evaluated = await contents.debugger.sendCommand("Runtime.evaluate", {
        returnByValue: true,
        expression: `(() => ({
          route: location.origin + location.pathname,
          visibility: document.visibilityState,
          dom_nodes: document.getElementsByTagName('*').length,
          buttons: document.querySelectorAll('button,[role="button"]').length,
          inputs: document.querySelectorAll('input,textarea,select').length,
          widgets: document.querySelectorAll('[data-widget-id]').length,
          long_tasks: performance.getEntriesByType('longtask').length,
          navigation_ms: Math.round(performance.getEntriesByType('navigation')[0]?.duration || 0)
        }))()`,
      });
      result.analytics = evaluated.result?.value || {};
    }
    return result;
  }

  async function execute(win, operation, payload = {}) {
    if (operation === "observability_enable") return enable(win, payload);
    if (operation === "observability_collect") return collect(payload);
    if (operation === "observability_disable") return disable("requested");
    if (operation === "observability_status") return status();
    return { ok: false, schema: SCHEMA, error: "observability_operation_unsupported" };
  }

  return { execute, status, disable };
}

module.exports = { createObservabilityKernel, boundedLeaseMs, SCHEMA };
