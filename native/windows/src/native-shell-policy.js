const APP_ID = "wasm-agent";
const DEFAULT_SERVER_URL = "http://127.0.0.1:8877";
const PWA_HOME_PATH = "/home";
const GOOGLE_AUTH_ORIGINS = new Set([
  "https://accounts.google.com",
  "https://oauth2.googleapis.com",
]);

function normalizeServerUrl(value, fallback = DEFAULT_SERVER_URL) {
  const raw = String(value || "").trim();
  if (!raw) return fallback;
  const withProtocol = /^https?:\/\//i.test(raw) ? raw : `http://${raw}`;
  try {
    const url = new URL(withProtocol);
    return url.toString().replace(/\/$/, "");
  } catch {
    return fallback;
  }
}

function sameOrigin(appUrl, targetUrl) {
  try {
    return new URL(appUrl).origin === new URL(targetUrl).origin;
  } catch {
    return false;
  }
}

function isGoogleAuthUrl(targetUrl) {
  try {
    return GOOGLE_AUTH_ORIGINS.has(new URL(targetUrl).origin);
  } catch {
    return false;
  }
}

function chromeLikeUserAgent(value) {
  return String(value || "")
    .replace(/\sElectron\/[^\s]+/gi, "")
    .replace(/\sWASM Agent\/[^\s]+/gi, "")
    .trim();
}

function backendHomeUrl(serverUrl) {
  try {
    return new URL(PWA_HOME_PATH, serverUrl).toString();
  } catch {
    return "";
  }
}

function payloadIdentifiesWrongApp(payload) {
  const text = JSON.stringify(payload || {}).toLowerCase();
  return text.includes("colmeio admin") || text.includes("google_login_client_id");
}

function payloadIdentifiesWasmAgent(payload) {
  if (!payload || typeof payload !== "object") return false;
  const markers = [
    payload.appId,
    payload.service,
    payload.name,
    payload.health && payload.health.appId,
    payload.health && payload.health.service,
    payload.health && payload.health.name,
  ].map((value) => String(value || "").toLowerCase());
  return markers.includes(APP_ID) || markers.includes("wasm agent");
}

module.exports = {
  APP_ID,
  DEFAULT_SERVER_URL,
  GOOGLE_AUTH_ORIGINS,
  PWA_HOME_PATH,
  backendHomeUrl,
  chromeLikeUserAgent,
  isGoogleAuthUrl,
  normalizeServerUrl,
  payloadIdentifiesWasmAgent,
  payloadIdentifiesWrongApp,
  sameOrigin,
};
