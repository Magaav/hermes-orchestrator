"use strict";

const assert = require("node:assert");
const { safeCookieSessionSummary } = require("./native-session-proof");

const summary = safeCookieSessionSummary({
  hasWaUid: true,
  cookieCount: 2,
  cookieMeta: [
    { name: "wa_uid", value: "never-return", domain: ".wa.colmeio.com", secure: true, httpOnly: true, session: false, expirationDate: 5000 },
    { name: "temporary", value: "never-return", domain: ".wa.colmeio.com", secure: true, httpOnly: false, session: true, expirationDate: 0 },
  ],
}, 1000);

assert.deepStrictEqual(summary, {
  schema: "hermes.wasm_agent.native_cookie_session_summary.v1",
  has_wa_uid: true,
  cookie_count: 2,
  persistent_cookie_count: 1,
  secure_cookie_count: 2,
  http_only_cookie_count: 1,
  production_domain_cookie_count: 2,
  earliest_expiration_date: 5000,
  latest_expiration_date: 5000,
  durable_expiration_present: true,
  redacted: true,
});
assert.doesNotMatch(JSON.stringify(summary), /never-return|wa\.colmeio\.com/);

const expired = safeCookieSessionSummary({ hasWaUid: false, cookieCount: 1, cookieMeta: [{ session: false, expirationDate: 900 }] }, 1000);
assert.strictEqual(expired.durable_expiration_present, false);
assert.strictEqual(expired.latest_expiration_date, null);
assert.strictEqual(safeCookieSessionSummary({ cookieMeta: [{ domain: "evilwa.colmeio.com" }] }, 1000).production_domain_cookie_count, 0);

console.log("native session proof tests passed");
