"use strict";

const DEFAULT_INTERVAL_MS = 6 * 60 * 60 * 1000;

function automaticUpdatesEnabled(env = process.env) {
  return String(env.WASM_AGENT_DISABLE_AUTOMATIC_UPDATES || "").trim() !== "1";
}

function automaticUpdatePayload(env = process.env) {
  return automaticUpdatesEnabled(env)
    ? { automatic: true, applyApproved: true, cacheBypass: true }
    : { automatic: false, applyApproved: false, disabled: true };
}

function startAutomaticUpdateLoop({ run, env = process.env, intervalMs = DEFAULT_INTERVAL_MS, setTimer = setTimeout, scheduleImmediate = queueMicrotask } = {}) {
  if (typeof run !== "function" || !automaticUpdatesEnabled(env)) return { started: false, reason: "automatic_updates_disabled" };
  let running = false;
  const invoke = async () => {
    if (running) return { ok: false, skipped: "update_check_in_progress" };
    running = true;
    try { return await run(automaticUpdatePayload(env)); }
    finally { running = false; }
  };
  scheduleImmediate(() => { void invoke(); });
  const scheduleNext = () => {
    const timer = setTimer(async () => { await invoke(); scheduleNext(); }, Math.max(60_000, intervalMs));
    timer.unref?.();
  };
  scheduleNext();
  return { started: true, initialDelayMs: 0, intervalMs, retention: "no_update_payload_retention" };
}

module.exports = { automaticUpdatesEnabled, automaticUpdatePayload, startAutomaticUpdateLoop };
