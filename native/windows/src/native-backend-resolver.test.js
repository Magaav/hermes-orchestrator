const assert = require("node:assert");
const {
  selectPreferredBackendResult,
  validateWasmAgentOrigin,
} = require("./native-backend-resolver");

function jsonResponse(payload, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return payload;
    },
  };
}

async function run() {
  const unavailable = await validateWasmAgentOrigin("http://127.0.0.1:8877", {}, 10, {
    fetchImpl: async () => jsonResponse({ error: "missing" }, 404),
  });
  assert.strictEqual(unavailable.ok, false, "candidate without available /config.json must be rejected");
  assert.strictEqual(unavailable.reason, "HTTP 404");

  const invalidJson = await validateWasmAgentOrigin("http://localhost:8877", {}, 10, {
    fetchImpl: async () => ({
      ok: true,
      status: 200,
      async json() {
        throw new Error("Unexpected token");
      },
    }),
  });
  assert.strictEqual(invalidJson.ok, false, "candidate with invalid /config.json JSON must be rejected");
  assert.match(invalidJson.reason, /invalid JSON/);

  const validNoGoogle = await validateWasmAgentOrigin("http://localhost:8877", {}, 10, {
    fetchImpl: async () => jsonResponse({ appId: "wasm-agent", service: "wasm-agent", auth: { googleClientIdConfigured: false } }),
  });
  assert.strictEqual(validNoGoogle.ok, true, "valid wasm-agent config can load as a backend");
  assert.strictEqual(validNoGoogle.preference, 1);

  const googleConfigured = await validateWasmAgentOrigin("http://10.0.0.167:8877", {}, 10, {
    fetchImpl: async () => jsonResponse({ appId: "wasm-agent", service: "wasm-agent", auth: { googleClientIdConfigured: true } }),
  });
  assert.strictEqual(googleConfigured.ok, true, "Google-configured wasm-agent config must be accepted");
  assert.strictEqual(googleConfigured.preference, 0);
  assert.strictEqual(googleConfigured.googleClientIdConfigured, true);

  const selected = selectPreferredBackendResult([validNoGoogle, unavailable, googleConfigured]);
  assert.strictEqual(selected.serverUrl, "http://10.0.0.167:8877", "Google-configured backend must be preferred");
}

run().then(() => {
  console.log("native backend resolver ok");
}).catch((error) => {
  console.error(error);
  process.exit(1);
});
