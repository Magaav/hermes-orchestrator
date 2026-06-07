window.__WASM_AGENT_DISABLE_SW__ = true;
window.__wasmAgentLastFatalError = null;

function reportBootFatal(kind, error, extra) {
  const fatal = {
    kind,
    message: String((error && error.message) || error || "").slice(0, 500),
    stack: String((error && error.stack) || "").slice(0, 1800),
    href: window.location.href,
    buildId: "boot",
    authSessionLoadPhase: "before_app_bootstrap",
    loadAuthSessionReached: false,
    ...(extra || {}),
  };
  window.__wasmAgentLastFatalError = fatal;
  try {
    fetch("/native/diagnostics", {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        schema: "hermes.wasm_agent.renderer_boot_fatal.v1",
        device_id: "renderer-boot",
        build_id: "boot",
        reason: kind,
        href: window.location.href,
        last_frontend_fatal_error: fatal,
      }),
    });
  } catch {
    // Best-effort only.
  }
}

window.addEventListener("error", (event) => {
  reportBootFatal("renderer_boot_error", event.error || event.message, {
    source: event.filename || "",
    line: event.lineno || 0,
    column: event.colno || 0,
  });
});

window.addEventListener("unhandledrejection", (event) => {
  reportBootFatal("renderer_boot_unhandled_rejection", event.reason || "Unhandled promise rejection");
});

if ("serviceWorker" in navigator) {
  const resetKey = "wasmAgent.swReset.v2";
  Promise.all([
    navigator.serviceWorker.getRegistrations().then((items) => Promise.all(items.map((item) => item.unregister()))),
    "caches" in window ? caches.keys().then((keys) => Promise.all(keys.map((key) => caches.delete(key)))) : Promise.resolve(),
  ]).then(() => {
    if (!sessionStorage.getItem(resetKey) && navigator.serviceWorker.controller) {
      sessionStorage.setItem(resetKey, "1");
      window.location.reload();
    }
  }).catch(() => {});
}
