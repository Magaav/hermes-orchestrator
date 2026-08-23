"use strict";

const SUMMARY_SCHEMA = "hermes.wasm_agent.native_cookie_session_summary.v1";

function isProductionCookieDomain(value) {
  const domain = String(value || "").trim().toLowerCase().replace(/^\./, "");
  return domain === "wa.colmeio.com" || domain.endsWith(".wa.colmeio.com");
}

function safeCookieSessionSummary(authCookie = {}, nowSeconds = Date.now() / 1000) {
  const metadata = Array.isArray(authCookie.cookieMeta)
    ? authCookie.cookieMeta.filter((item) => item && typeof item === "object")
    : [];
  const futurePersistent = metadata.filter((item) => (
    item.session === false
    && Number.isFinite(Number(item.expirationDate))
    && Number(item.expirationDate) > nowSeconds
  ));
  const expirations = futurePersistent.map((item) => Number(item.expirationDate));
  return {
    schema: SUMMARY_SCHEMA,
    has_wa_uid: authCookie.hasWaUid === true,
    cookie_count: Math.max(0, Number(authCookie.cookieCount) || metadata.length),
    persistent_cookie_count: futurePersistent.length,
    secure_cookie_count: metadata.filter((item) => item.secure === true).length,
    http_only_cookie_count: metadata.filter((item) => item.httpOnly === true).length,
    production_domain_cookie_count: metadata.filter((item) => isProductionCookieDomain(item.domain)).length,
    earliest_expiration_date: expirations.length ? Math.min(...expirations) : null,
    latest_expiration_date: expirations.length ? Math.max(...expirations) : null,
    durable_expiration_present: futurePersistent.length > 0,
    redacted: true,
  };
}

module.exports = { SUMMARY_SCHEMA, safeCookieSessionSummary };
