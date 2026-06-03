const { APP_ID, payloadIdentifiesWasmAgent, payloadIdentifiesWrongApp } = require("./native-shell-policy");

async function fetchJsonProbe(serverUrl, probePath, timeoutMs = 900, fetchImpl = fetch) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetchImpl(new URL(probePath, serverUrl).toString(), {
      method: "GET",
      headers: { "X-Wasm-Agent-Native-Probe": APP_ID },
      signal: controller.signal,
    });
    if (!response.ok) return { ok: false, status: response.status, payload: null, reason: `HTTP ${response.status}` };
    try {
      return { ok: true, status: response.status, payload: await response.json() };
    } catch (error) {
      return {
        ok: false,
        status: response.status,
        payload: null,
        reason: `invalid JSON${error && error.message ? `: ${error.message}` : ""}`,
      };
    }
  } finally {
    clearTimeout(timer);
  }
}

async function validateWasmAgentOrigin(serverUrl, current = {}, timeoutMs = 900, options = {}) {
  const checks = [];
  const fetchImpl = options.fetchImpl || fetch;
  try {
    const probe = await fetchJsonProbe(serverUrl, "/config.json", timeoutMs, fetchImpl);
    const payload = probe.payload && typeof probe.payload === "object" ? probe.payload : null;
    const wrongApp = payloadIdentifiesWrongApp(payload);
    const wasmAgent = payloadIdentifiesWasmAgent(payload);
    const validConfig = Boolean(payload && typeof payload === "object" && (payload.auth || payload.appId || payload.service || payload.name || payload.version));
    const googleClientIdConfigured = Boolean(payload?.auth?.googleClientIdConfigured || payload?.auth?.googleClientId);
    checks.push({
      path: "/config.json",
      status: probe.status,
      ok: probe.ok,
      wasmAgent,
      wrongApp,
      validConfig,
      googleClientIdConfigured,
      reason: probe.reason || "",
    });
    if (!probe.ok) return { ok: false, serverUrl, reason: probe.reason || "config_json_unavailable", checks, googleClientIdConfigured: false };
    if (wrongApp) return { ok: false, serverUrl, reason: "wrong_app_identity", checks, googleClientIdConfigured };
    if (googleClientIdConfigured) return { ok: true, serverUrl, checks, googleClientIdConfigured, preference: 0 };
    if (validConfig && wasmAgent) return { ok: true, serverUrl, checks, googleClientIdConfigured, preference: 1 };
    if (validConfig) return { ok: true, serverUrl, checks, googleClientIdConfigured, preference: 2 };
    return { ok: false, serverUrl, reason: "invalid_config_json", checks, googleClientIdConfigured: false };
  } catch (error) {
    const message = String(error && error.message ? error.message : error);
    checks.push({ path: "/config.json", ok: false, reason: message });
    return { ok: false, serverUrl, reason: message || "config_json_unavailable", checks, deviceId: current.deviceId, googleClientIdConfigured: false };
  }
  return { ok: false, serverUrl, reason: "config_json_unavailable", checks, deviceId: current.deviceId, googleClientIdConfigured: false };
}

function selectPreferredBackendResult(results = []) {
  return results
    .filter((result) => result && result.ok)
    .sort((a, b) => (a.preference ?? 99) - (b.preference ?? 99))[0] || null;
}

module.exports = {
  fetchJsonProbe,
  selectPreferredBackendResult,
  validateWasmAgentOrigin,
};
