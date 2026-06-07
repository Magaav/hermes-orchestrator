"use strict";

const REDACTION = "[REDACTED]";

const SENSITIVE_KEY_HINTS = [
  "authorization",
  "accesstoken",
  "cookie",
  "setcookie",
  "idtoken",
  "refreshtoken",
  "token",
  "secret",
  "password",
  "credential",
  "clientsecret",
  "apikey",
  "authcode",
  "wauid",
  "session",
];

const SENSITIVE_PARAM_NAMES = new Set([
  "access_token",
  "auth_code",
  "client_secret",
  "code",
  "credential",
  "id_token",
  "nonce",
  "password",
  "refresh_token",
  "secret",
  "token",
  "wa_uid",
]);

const SAFE_NATIVE_EVIDENCE_KEYS = new Set([
  "androidauthsession",
  "nativeandroidauthsession",
  "nativecorrelationid",
  "correlationid",
  "installdevicehash",
  "buildid",
  "safecookiesessionsummary",
  "cookiecount",
  "cookienames",
  "haswauid",
  "hasandroidauthsessioncookie",
  "cookieset",
]);

function normalizedKey(key) {
  return String(key || "").replace(/[^a-z0-9]/gi, "").toLowerCase();
}

function isSensitiveKey(key) {
  const normalized = normalizedKey(key);
  if (!normalized) return false;
  return SENSITIVE_KEY_HINTS.some((hint) => normalized === hint || normalized.endsWith(hint));
}

function looksLikeAndroidAuthSession(value) {
  const text = String(value || "").trim();
  return /^(fixture-session-[A-Za-z0-9._:-]{8,}|[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})$/i.test(text);
}

function isSafeNativeEvidence(key, value) {
  const normalized = normalizedKey(key);
  if (SAFE_NATIVE_EVIDENCE_KEYS.has(normalized)) return true;
  return normalized === "session" && looksLikeAndroidAuthSession(value);
}

function redactUrl(value) {
  if (!/^https?:\/\//i.test(value)) return value;
  try {
    const url = new URL(value);
    for (const key of Array.from(url.searchParams.keys())) {
      if (SENSITIVE_PARAM_NAMES.has(key.toLowerCase()) || isSensitiveKey(key)) {
        url.searchParams.set(key, REDACTION);
      }
    }
    return url.toString();
  } catch {
    return value;
  }
}

function redactString(value) {
  let redacted = redactUrl(String(value));
  redacted = redacted.replace(/(Bearer\s+)[A-Za-z0-9._~+/=-]+/gi, `$1${REDACTION}`);
  redacted = redacted.replace(
    /(^|[?&\s"'<>;])((?:access_token|auth_code|client_secret|code|credential|id_token|password|refresh_token|secret|token|wa_uid)=)[^&\s"'<>]+/gi,
    `$1$2${REDACTION}`,
  );
  redacted = redacted.replace(/((?:Cookie|Set-Cookie):\s*)[^\r\n]+/gi, `$1${REDACTION}`);
  return redacted;
}

function redactValue(value, key = "", depth = 0, seen = new WeakSet()) {
  if (isSensitiveKey(key) && !isSafeNativeEvidence(key, value)) return REDACTION;
  if (value == null) return value;
  if (typeof value === "string") return redactString(value);
  if (typeof value === "number" || typeof value === "boolean") return value;
  if (typeof value === "bigint") return String(value);
  if (typeof value === "function") return "[Function]";
  if (typeof value !== "object") return String(value);
  if (seen.has(value)) return "[Circular]";
  if (depth > 8) return "[MaxDepth]";
  seen.add(value);
  if (Array.isArray(value)) {
    return value.slice(0, 200).map((item) => redactValue(item, "", depth + 1, seen));
  }
  const output = {};
  for (const [entryKey, entryValue] of Object.entries(value)) {
    output[entryKey] = redactValue(entryValue, entryKey, depth + 1, seen);
  }
  return output;
}

module.exports = {
  REDACTION,
  isSensitiveKey,
  redactString,
  redactValue,
};
