(() => {
  const ANDROID_APP_BOOT_BUILD = "20260630-route-contracts";
  const ANDROID_RUNTIME_MODE_STORAGE_KEY = "wasmAgent.androidRuntimeMode.v1";

  function androidNativeBootHint() {
    try {
      const params = new URL(window.location.href).searchParams;
      const hint = `${params.get("native") || ""} ${params.get("shell") || ""}`.toLowerCase();
      return hint.includes("android") || Boolean(window.wasmAgentAndroid);
    } catch {
      return Boolean(window.wasmAgentAndroid);
    }
  }

  function nativeDeviceId() {
    try {
      const params = new URL(window.location.href).searchParams;
      const nativeState = window.wasmAgentAndroid?.runtimeState?.() || window.wasmAgentAndroid?.state || {};
      const buildId = String(nativeState?.build?.build_id || params.get("buildId") || "android-loader").trim();
      const installHash = String(nativeState?.install_device_hash || params.get("install_device_hash") || "").trim();
      return installHash ? `android-${buildId}-${installHash}` : `android-${buildId}`;
    } catch {
      return "android-loader";
    }
  }

  function selectedAndroidRuntimeMode(isAndroid) {
    if (!isAndroid) return "web-full";
    let params = null;
    try {
      params = new URL(window.location.href).searchParams;
    } catch {
      params = new URLSearchParams();
    }
    const candidates = [
      params.get("android_shell"),
      params.get("androidShell"),
      params.get("android_runtime"),
      params.get("androidRuntime"),
      params.get("native_debug_shell"),
    ]
      .map((item) => String(item || "").trim().toLowerCase())
      .filter(Boolean);
    if (candidates.some((item) => [
      "debug-lite",
      "lite",
      "android-lite",
      "debug",
    ].includes(item))) {
      return "debug-lite";
    }
    if (candidates.some((item) => [
      "user-full",
      "full",
      "shared",
      "shared-full",
      "pwa",
      "windows",
      "default",
    ].includes(item))) {
      return "user-full";
    }
    try {
      const stored = String(localStorage.getItem(ANDROID_RUNTIME_MODE_STORAGE_KEY) || "").trim().toLowerCase();
      if ([
        "user-full",
        "full",
        "shared",
        "shared-full",
        "pwa",
      ].includes(stored)) return "user-full";
    } catch {
      // Runtime mode storage is optional.
    }
    return "user-full";
  }

  function androidFlag(name) {
    try {
      const value = String(new URL(window.location.href).searchParams.get(name) || "").trim().toLowerCase();
      return value === "1" || value === "true" || value === "yes" || value === "on";
    } catch {
      return false;
    }
  }

  function reportLoaderFailure(target, error) {
    const message = String(error?.message || error || "script load failed");
    window.__wasmAgentLastFatalError = {
      kind: "app-loader-script-failed",
      target,
      message,
      timestamp: new Date().toISOString(),
    };
    try {
      const now = Math.round(performance.now());
      const bootTrace = {
        schema: "hermes.wasm_agent.client_boot_trace.v1",
        reason: "app_loader_script_failed",
        boot_id: `boot-loader-${Date.now().toString(36)}`,
        started_at: new Date().toISOString(),
        elapsed_ms: now,
        href: window.location.href,
        user_agent: navigator.userAgent || "",
        build_id: "android-loader",
        native_shell: { native: "android", shell: "android-webview", loader_target: target },
        app: {
          authenticated: false,
          active_panel: "home",
          app_status: document.getElementById("app")?.dataset?.status || "",
          app_auth: document.getElementById("app")?.dataset?.auth || "",
          native_app_ready_notified: false,
          android_lite_boot: true,
        },
        marks: [{ at_ms: now, phase: "app_loader_script_failed", data: { target, message } }],
        fetches: [],
        inputs: [],
        long_tasks: [],
        errors: [{ at_ms: now, message }],
        slow_resources: [],
      };
      void fetch("/native/diagnostics", {
        method: "POST",
        cache: "no-store",
        keepalive: true,
        headers: {
          "Accept": "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          schema: "hermes.wasm_agent.client_boot_trace_upload.v1",
          device_id: nativeDeviceId(),
          build_id: "android-loader",
          reason: "app_loader_script_failed",
          boot_trace: bootTrace,
        }),
      });
    } catch {
      // Loader diagnostics are best effort and must never block app startup.
    }
  }

  const isAndroid = androidNativeBootHint();
  const runtimeMode = selectedAndroidRuntimeMode(isAndroid);
  const useDebugLite = isAndroid && runtimeMode === "debug-lite";
  const perfSafeMode = isAndroid && (androidFlag("perfSafeMode") || androidFlag("perf_safe_mode"));
  window.__WASM_AGENT_ANDROID_RUNTIME_MODE__ = runtimeMode;
  window.__WASM_AGENT_ANDROID_DEBUG_SHELL__ = useDebugLite;
  window.__WASM_AGENT_ANDROID_DEBUG_SHELL_QUERY__ = "android_shell=debug-lite";
  window.__WASM_AGENT_ANDROID_PERF_SAFE_MODE__ = perfSafeMode;
  window.__WASM_AGENT_ANDROID_BRIDGE_DIAGNOSTICS__ = perfSafeMode ? "off" : "sampled";
  window.__WASM_AGENT_ANDROID_WAKE_STARTUP__ = perfSafeMode ? "off" : "deferred";
  const target = useDebugLite
    ? `/android-app.js?v=${ANDROID_APP_BOOT_BUILD}`
    : `/app.js?v=${ANDROID_APP_BOOT_BUILD}`;
  const script = document.createElement("script");
  script.type = "module";
  script.src = target;
  script.dataset.wasmAgentRuntime = isAndroid ? runtimeMode : "web-full";
  script.dataset.androidRuntimeMode = runtimeMode;
  script.addEventListener("error", () => reportLoaderFailure(target, new Error("module script load failed")), { once: true });
  const anchor = document.currentScript;
  if (anchor?.parentNode) anchor.parentNode.insertBefore(script, anchor.nextSibling);
  else (document.head || document.documentElement).appendChild(script);
})();
