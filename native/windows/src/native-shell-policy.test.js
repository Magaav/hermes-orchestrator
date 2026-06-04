const assert = require("node:assert");
const {
  APP_ID,
  backendHomeUrl,
  chromeLikeUserAgent,
  isGoogleAuthUrl,
  normalizeServerUrl,
  payloadIdentifiesWasmAgent,
  payloadIdentifiesWrongApp,
  sameOrigin,
} = require("./native-shell-policy");

assert.strictEqual(APP_ID, "wasm-agent");
assert.strictEqual(require("./native-shell-policy").DEFAULT_SERVER_URL, "https://wa.colmeio.com");
assert.strictEqual(normalizeServerUrl("localhost:8877"), "http://localhost:8877");
assert.strictEqual(normalizeServerUrl("https://wa.example.test/"), "https://wa.example.test");
assert.strictEqual(backendHomeUrl("https://wa.example.test/base"), "https://wa.example.test/home");
assert.strictEqual(sameOrigin("https://wa.example.test/home", "https://wa.example.test/auth/google/callback"), true);
assert.strictEqual(sameOrigin("https://wa.example.test/home", "https://accounts.google.com/o/oauth2"), false);
assert.strictEqual(isGoogleAuthUrl("https://accounts.google.com/gsi/client"), true);
assert.strictEqual(isGoogleAuthUrl("https://oauth2.googleapis.com/tokeninfo"), true);
assert.strictEqual(isGoogleAuthUrl("https://evil.example.test/accounts.google.com"), false);
assert.strictEqual(
  chromeLikeUserAgent("Mozilla/5.0 Chrome/120 Safari/537.36 Electron/42.3.2 WASM Agent/0.1.0"),
  "Mozilla/5.0 Chrome/120 Safari/537.36"
);
assert.strictEqual(payloadIdentifiesWasmAgent({ appId: "wasm-agent" }), true);
assert.strictEqual(payloadIdentifiesWasmAgent({ health: { service: "wasm-agent" } }), true);
assert.strictEqual(payloadIdentifiesWasmAgent({ name: "Colmeio Admin" }), false);
assert.strictEqual(payloadIdentifiesWrongApp({ title: "Colmeio Admin" }), true);
assert.strictEqual(payloadIdentifiesWrongApp({ error: "Set GOOGLE_LOGIN_CLIENT_ID" }), true);

console.log("native shell policy ok");
