"use strict";
const assert = require("node:assert");
const { normalizeUrl, portScript, run } = require("./windows-cdp-navigate");

assert.strictEqual(normalizeUrl("javascript:alert(1)"), "");
assert.strictEqual(normalizeUrl("https://web.whatsapp.com"), "https://web.whatsapp.com/");
assert(portScript().includes("DevToolsActivePort"));

(async () => {
  const phases = [];
  const calls = [];
  const result = await run({ args: { url: "https://web.whatsapp.com" }, markPhase: (phase) => phases.push(phase) }, {
    platform: "win32",
    discover: async () => ({ ok: true, stdout: '{"port":55212,"processId":19888}' }),
    requestJson: async (request) => {
      calls.push(request);
      if (!request.method && calls.length === 1) return { ok: true, value: [] };
      if (request.method === "PUT") return { ok: true, value: { id: "target-1", url: "https://web.whatsapp.com/" } };
      return { ok: true, value: [{ id: "target-1", url: "https://web.whatsapp.com/" }] };
    },
  });
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.observedUrl, "https://web.whatsapp.com/");
  assert.deepStrictEqual(result.proof, ["windows.browser.cdp.navigation.observed"]);
  assert.deepStrictEqual(phases, ["persistent_cdp_navigation_started", "persistent_cdp_navigation_observed"]);
  assert.strictEqual(calls[1].method, "PUT");
  assert(calls[1].path.includes(encodeURIComponent("https://web.whatsapp.com/")));

  const reused = await run({ args: { url: "https://web.whatsapp.com" } }, {
    platform: "win32",
    discover: async () => ({ ok: true, stdout: '{"port":55212,"processId":19888}' }),
    requestJson: async () => ({ ok: true, value: [{ id: "existing-1", url: "https://web.whatsapp.com/" }] }),
  });
  assert.strictEqual(reused.ok, true);
  assert.strictEqual(reused.reusedTarget, true);
  assert.strictEqual(reused.targetId, "existing-1");
  console.log("windows CDP navigation proof tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
