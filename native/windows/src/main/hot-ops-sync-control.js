"use strict";

const SCHEMA = "hermes.wasm_agent.windows_hot_ops_sync_lifecycle.v1";
const DEFAULT_STUCK_MS = 120_000;

function completionProjection(result = {}) {
  return {
    feedBundleId: String(result.feedBundleId || ""),
    cachedBundleId: String(result.cachedBundleId || ""),
    moduleSha: String(result.moduleSha || ""),
    bundleCount: Array.isArray(result.bundles) ? result.bundles.length : 0,
  };
}

function createHotOpsSyncControl({ sync, list, logs = () => [], audit = () => {}, now = () => Date.now(), stuckMs = DEFAULT_STUCK_MS } = {}) {
  if (typeof sync !== "function" || typeof list !== "function") throw new TypeError("hot_ops_sync_dependencies_required");
  let generation = 0;
  let active = null;
  let state = { schema: SCHEMA, phase: "idle", generation: 0, acceptedAt: "", startedAt: "", completedAt: "", ageMs: 0, stuck: false, ok: null, changed: null, error: "", feedBundleId: "", cachedBundleId: "", moduleSha: "", bundleCount: 0 };

  const snapshot = () => {
    const ageMs = state.phase === "running" ? Math.max(0, now() - Date.parse(state.startedAt || state.acceptedAt)) : 0;
    return { ...state, ageMs, stuck: state.phase === "running" && ageMs >= stuckMs };
  };

  const start = (payload = {}, operation = "sync_downloaded_hot_ops") => {
    if (active) return { ok: true, operation, accepted: true, deduplicated: true, completed: false, syncLifecycle: snapshot(), logsTail: logs() };
    generation += 1;
    const acceptedAt = new Date(now()).toISOString();
    state = { schema: SCHEMA, phase: "running", generation, acceptedAt, startedAt: acceptedAt, completedAt: "", ageMs: 0, stuck: false, ok: null, changed: null, error: "", feedBundleId: "", cachedBundleId: "", moduleSha: "", bundleCount: 0 };
    const current = generation;
    audit({ action: "hot_ops_sync_started", generation: current, operation });
    active = Promise.resolve()
      .then(() => sync({ ...payload, forceSync: true }))
      .then((result) => {
        state = { ...state, phase: result?.ok === true ? "completed" : "failed", completedAt: new Date(now()).toISOString(), ok: result?.ok === true, changed: result?.changed === true, error: String(result?.error || ""), ...completionProjection(result) };
        audit({ action: "hot_ops_sync_finished", generation: current, ok: state.ok, changed: state.changed });
      }, (error) => {
        state = { ...state, phase: "failed", completedAt: new Date(now()).toISOString(), ok: false, changed: false, error: String(error?.message || error) };
        audit({ action: "hot_ops_sync_failed", generation: current, error: state.error });
      })
      .finally(() => { if (current === generation) active = null; });
    return { ok: true, operation, accepted: true, deduplicated: false, completed: false, syncLifecycle: snapshot(), logsTail: logs() };
  };

  const inspect = (payload = {}, operation = "list_hot_operations") => ({ ...list(payload), operation, syncLifecycle: snapshot() });
  const handle = (type, payload = {}) => {
    if (type === "list_hot_operations") return { handled: true, result: inspect(payload, type) };
    if (type === "refresh_downloaded_hot_ops" || type === "sync_downloaded_hot_ops") return { handled: true, result: start(payload, type) };
    return { handled: false, result: null };
  };

  return { handle, inspect, snapshot, start };
}

module.exports = { DEFAULT_STUCK_MS, SCHEMA, completionProjection, createHotOpsSyncControl };
