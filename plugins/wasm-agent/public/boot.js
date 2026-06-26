window.__WASM_AGENT_DISABLE_SW__ = true;
window.__wasmAgentLastFatalError = null;

(() => {
  if (window.__WASM_AGENT_ANDROID_PREPAINT_BOOT__) return;
  window.__WASM_AGENT_ANDROID_PREPAINT_BOOT__ = true;
  const AUTH_USER_STORAGE_KEY = "wasmAgent.authUser.v1";
  const CONFIG_STORAGE_KEY = "wasmAgent.clientConfig.v1";
  const CACHE_MAX_AGE_MS = 7 * 24 * 60 * 60 * 1000;
  let observer = null;
  let stopTimer = 0;

  const mark = (name) => {
    try {
      performance.mark(name);
    } catch {
      // Performance marks are diagnostic only.
    }
  };

  const androidPrepaintHint = () => {
    try {
      const params = new URL(window.location.href).searchParams;
      const nativeHint = `${params.get("native") || ""} ${params.get("shell") || ""}`.toLowerCase();
      return nativeHint.includes("android") || Boolean(window.wasmAgentAndroid);
    } catch {
      return Boolean(window.wasmAgentAndroid);
    }
  };

  const readCached = (key) => {
    try {
      const cached = JSON.parse(localStorage.getItem(key) || "null");
      const cachedAt = Date.parse(cached?.cached_at || "");
      if (!Number.isFinite(cachedAt) || Date.now() - cachedAt > CACHE_MAX_AGE_MS) return null;
      return cached;
    } catch {
      return null;
    }
  };

  const stopWatching = () => {
    if (observer) observer.disconnect();
    observer = null;
    if (stopTimer) window.clearTimeout(stopTimer);
    stopTimer = 0;
  };

  const applyAndroidPrepaintShell = () => {
    if (window.__WASM_AGENT_PREPAINT_SHELL) return "painted";
    const app = document.getElementById("app");
    if (!app) return "waiting";
    if (!androidPrepaintHint()) return "done";
    const cachedUser = readCached(AUTH_USER_STORAGE_KEY)?.user;
    if (!cachedUser || typeof cachedUser !== "object") return "done";
    const cachedConfig = readCached(CONFIG_STORAGE_KEY)?.config || null;
    const shell = {
      schema: "hermes.wasm_agent.android_prepaint_shell.v1",
      authenticated: true,
      route: `${window.location.pathname || "/"}${window.location.search || ""}`,
      visibleAtMs: Math.round(performance.now()),
      configCached: Boolean(cachedConfig?.auth?.googleClientId),
      user: {
        id: String(cachedUser.id || ""),
        email: String(cachedUser.email || ""),
        name: String(cachedUser.name || ""),
        picture_url: String(cachedUser.picture_url || ""),
        role: String(cachedUser.role || ""),
      },
    };
    app.dataset.auth = "ready";
    app.dataset.status = "ready";
    app.dataset.androidPrepaint = "authenticated";
    app.classList.add("android-prepaint-authenticated");
    window.__WASM_AGENT_PREPAINT_SHELL = shell;
    window.__WASM_AGENT_PREPAINT_SHELL_AFTER_PAINT__ = new Promise((resolve) => {
      const markAfterPaint = () => {
        shell.afterPaintAtMs = Math.round(performance.now());
        app.dataset.androidPrepaintAfterPaint = "true";
        mark("wasm-agent:pre_module_cached_authenticated_shell_after_paint");
        resolve(shell);
      };
      if (typeof window.requestAnimationFrame === "function") {
        window.requestAnimationFrame(() => window.setTimeout(markAfterPaint, 0));
      } else {
        window.setTimeout(markAfterPaint, 0);
      }
    });
    mark("wasm-agent:pre_module_cached_authenticated_shell_visible");
    return "painted";
  };

  const decorateAndroidPrepaintShell = () => {
    const shell = window.__WASM_AGENT_PREPAINT_SHELL;
    if (!shell?.authenticated) return false;
    if (shell.decoratedAtMs) return true;
    const launcherLogin = document.getElementById("launcherLogin");
    const loginAvatar = document.getElementById("loginAvatar");
    const loginButton = document.getElementById("loginButton");
    const loginTitle = document.getElementById("loginTitle");
    const loginMeta = document.getElementById("loginMeta");
    const loginMessage = document.getElementById("loginMessage");
    if (!launcherLogin || !loginAvatar || !loginButton) return false;
    const user = shell.user || {};
    const label = String(user.name || user.email || "Account").trim();
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
    shell.decoratedAtMs = Math.round(performance.now());
    mark("wasm-agent:pre_module_cached_authenticated_shell_decorated");
    return true;
  };

  const tick = () => {
    const status = applyAndroidPrepaintShell();
    const decorated = decorateAndroidPrepaintShell();
    if (status === "done" || (status === "painted" && decorated)) stopWatching();
  };

  if (document.documentElement) {
    observer = new MutationObserver(tick);
    observer.observe(document.documentElement, { childList: true, subtree: true });
  }
  document.addEventListener("DOMContentLoaded", tick, { once: true });
  window.addEventListener("load", () => {
    tick();
    window.setTimeout(stopWatching, 0);
  }, { once: true });
  stopTimer = window.setTimeout(stopWatching, 10000);
  tick();
})();

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
