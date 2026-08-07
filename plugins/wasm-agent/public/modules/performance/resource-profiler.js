const RESOURCE_PROFILE_MAX_ENTRIES = 320;
const RESOURCE_PROFILE_SLOW_MS = 24;
const RESOURCE_PROFILE_LONG_MS = 80;

const isWeakMapKey = (value) => (typeof value === "object" && value !== null) || typeof value === "function";

export function installResourceProfiler(runtime = {}) {
  const windowRef = runtime.windowRef || globalThis.window;
  if (!windowRef || windowRef.__wasmAgentResourceProfiler?.installed) return windowRef?.__wasmAgentResourceProfiler;
  const documentRef = runtime.documentRef || globalThis.document;
  const EventTargetCtor = runtime.EventTargetCtor || globalThis.EventTarget;
  const performanceRef = runtime.performanceRef || globalThis.performance;
  if (!EventTargetCtor?.prototype || typeof performanceRef?.now !== "function") return undefined;

  const profiler = {
    installed: true,
    startedAt: Date.now(),
    seq: 0,
    entries: new Map(),
    slow: [],
    originals: {},
  };
  const cleanLabel = (value = "", fallback = "anonymous") => String(value || fallback).replace(/\s+/g, " ").slice(0, 180);
  const remember = (label, durationMs, detail = {}) => {
    const duration = Number(durationMs || 0);
    const key = cleanLabel(label);
    const existing = profiler.entries.get(key) || {
      label: key, count: 0, total_ms: 0, max_ms: 0, slow_count: 0, last_ms: 0, last_at: 0, detail,
    };
    existing.count += 1;
    existing.total_ms = Math.round((existing.total_ms + duration) * 100) / 100;
    existing.max_ms = Math.max(existing.max_ms, Math.round(duration * 100) / 100);
    existing.last_ms = Math.round(duration * 100) / 100;
    existing.last_at = Date.now();
    existing.detail = { ...existing.detail, ...detail };
    if (duration >= RESOURCE_PROFILE_SLOW_MS) existing.slow_count += 1;
    profiler.entries.set(key, existing);
    if (profiler.entries.size > RESOURCE_PROFILE_MAX_ENTRIES) {
      const oldest = Array.from(profiler.entries.values()).sort((a, b) => Number(a.last_at || 0) - Number(b.last_at || 0))[0];
      if (oldest) profiler.entries.delete(oldest.label);
    }
    if (duration >= RESOURCE_PROFILE_LONG_MS) {
      profiler.slow.push({ at: new Date().toISOString(), label: key, duration_ms: Math.round(duration * 100) / 100, detail });
      while (profiler.slow.length > 80) profiler.slow.shift();
    }
  };
  const wrapCallback = (callback, label, detail = {}) => {
    if (typeof callback !== "function" || callback.__wasmAgentProfileWrapped) return callback;
    const wrapped = function wasmAgentProfiledCallback(...args) {
      const started = performanceRef.now();
      try {
        return callback.apply(this, args);
      } finally {
        remember(label, performanceRef.now() - started, detail);
      }
    };
    try {
      Object.defineProperty(wrapped, "__wasmAgentProfileWrapped", { value: true });
      Object.defineProperty(wrapped, "__wasmAgentOriginalCallback", { value: callback });
    } catch {}
    return wrapped;
  };
  const callbackName = (callback) => cleanLabel(callback?.name || "anonymous");
  const creationSite = () => {
    try {
      const lines = String(new Error().stack || "").split("\n").map((line) => line.trim());
      const site = lines.find((line) => line.includes("/app.js")
        && !line.includes("creationSite")
        && !line.includes("wrapCallback")
        && !line.includes("profiledAddEventListener")
        && !line.includes("profiledSetTimeout")
        && !line.includes("profiledSetInterval")
        && !line.includes("profiledRequestAnimationFrame"));
      return cleanLabel(site || lines[3] || "", "");
    } catch {
      return "";
    }
  };
  const targetName = (target) => {
    if (target === windowRef) return "window";
    if (target === documentRef) return "document";
    if (target?.id) return `#${target.id}`;
    if (target?.className && typeof target.className === "string") return `.${target.className.split(/\s+/)[0]}`;
    if (target?.tagName) return target.tagName.toLowerCase();
    return target?.constructor?.name || "EventTarget";
  };

  profiler.originals.addEventListener = EventTargetCtor.prototype.addEventListener;
  profiler.originals.removeEventListener = EventTargetCtor.prototype.removeEventListener;
  profiler.originals.setTimeout = windowRef.setTimeout;
  profiler.originals.setInterval = windowRef.setInterval;
  profiler.originals.requestAnimationFrame = windowRef.requestAnimationFrame;
  profiler.listenerMap = new WeakMap();
  EventTargetCtor.prototype.addEventListener = function profiledAddEventListener(type, listener, options) {
    let nextListener = listener;
    if (typeof listener === "function" && isWeakMapKey(this)) {
      const name = callbackName(listener);
      const site = name === "anonymous" ? creationSite() : "";
      nextListener = wrapCallback(listener, `listener:${targetName(this)}:${type}:${name}${site ? `:${site}` : ""}`, {
        kind: "listener", target: targetName(this), type: String(type || ""), callback: name, site,
      });
      let targetMap = profiler.listenerMap.get(this);
      if (!targetMap) {
        targetMap = new WeakMap();
        profiler.listenerMap.set(this, targetMap);
      }
      targetMap.set(listener, nextListener);
    }
    return profiler.originals.addEventListener.call(this, type, nextListener, options);
  };
  EventTargetCtor.prototype.removeEventListener = function profiledRemoveEventListener(type, listener, options) {
    const mapped = isWeakMapKey(this)
      ? profiler.listenerMap.get(this)?.get(listener) || listener?.__wasmAgentOriginalCallback || listener
      : listener;
    return profiler.originals.removeEventListener.call(this, type, mapped, options);
  };
  windowRef.setTimeout = function profiledSetTimeout(callback, delay, ...args) {
    const name = callbackName(callback);
    const site = name === "anonymous" ? creationSite() : "";
    return profiler.originals.setTimeout.call(windowRef, wrapCallback(callback, `timer:setTimeout:${name}${site ? `:${site}` : ""}`, {
      kind: "timer", delay_ms: Number(delay || 0), site,
    }), delay, ...args);
  };
  windowRef.setInterval = function profiledSetInterval(callback, delay, ...args) {
    const name = callbackName(callback);
    const site = name === "anonymous" ? creationSite() : "";
    return profiler.originals.setInterval.call(windowRef, wrapCallback(callback, `timer:setInterval:${name}${site ? `:${site}` : ""}`, {
      kind: "interval", delay_ms: Number(delay || 0), site,
    }), delay, ...args);
  };
  if (typeof windowRef.requestAnimationFrame === "function") {
    windowRef.requestAnimationFrame = function profiledRequestAnimationFrame(callback) {
      return profiler.originals.requestAnimationFrame.call(windowRef, wrapCallback(callback, `raf:${callbackName(callback)}`, { kind: "raf" }));
    };
  }
  profiler.snapshot = (options = {}) => {
    const entries = Array.from(profiler.entries.values());
    const sortKey = options.sort || "total_ms";
    return {
      schema: "hermes.wasm_agent.resource_profile.v1",
      captured_at: new Date().toISOString(),
      started_at: new Date(profiler.startedAt).toISOString(),
      entry_count: entries.length,
      top_total: entries.slice().sort((a, b) => Number(b.total_ms || 0) - Number(a.total_ms || 0)).slice(0, Number(options.limit || 24)),
      top_max: entries.slice().sort((a, b) => Number(b.max_ms || 0) - Number(a.max_ms || 0)).slice(0, Number(options.limit || 24)),
      top_count: entries.slice().sort((a, b) => Number(b.count || 0) - Number(a.count || 0)).slice(0, Number(options.limit || 24)),
      sorted: entries.slice().sort((a, b) => Number(b[sortKey] || 0) - Number(a[sortKey] || 0)).slice(0, Number(options.limit || 24)),
      slow_tail: profiler.slow.slice(-Number(options.slowLimit || 24)),
    };
  };
  profiler.reset = () => {
    profiler.entries.clear();
    profiler.slow = [];
    profiler.startedAt = Date.now();
    return profiler.snapshot();
  };
  windowRef.__wasmAgentResourceProfiler = profiler;
  return profiler;
}
