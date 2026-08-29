"use strict";

const assert = require("node:assert");
const { normalize, powershellScript, run } = require("./windows-private-cdp");

const ready = normalize({ sessionId: "private-cdp-abc", processId: 42, port: 49152,
  endpoint: "http://127.0.0.1:49152", browser: "Chrome/140", protocolVersion: "1.3",
  webSocketDebuggerUrl: "ws://127.0.0.1:49152/devtools/browser/abc" });
assert.strictEqual(ready.ok, true);
assert.strictEqual(ready.realm, "browser_cdp_incognito");
assert.deepStrictEqual(ready.proof, ["windows.browser.cdp.incognito.ready"]);
assert.strictEqual(normalize({ processId: 42, port: 9223, endpoint: "http://0.0.0.0:9223", webSocketDebuggerUrl: "ws://0.0.0.0:9223/x" }).ok, false);

const script = powershellScript("incognito");
for (const required of ["--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0", "--incognito", "DevToolsActivePort", "/json/version", "Wait-Process"]) assert(script.includes(required));
assert(!script.includes("context.args"));

(async () => {
  const phases = [];
  const result = await run({ operation: { name: "open_windows_cdp_incognito" }, markPhase: (phase) => phases.push(phase) }, { platform: "win32", executeOpen: async () => ({ ok: true, stdout: JSON.stringify({
    sessionId: "private-cdp-fixture", processId: 77, port: 50001, endpoint: "http://127.0.0.1:50001",
    browser: "Chrome/140", protocolVersion: "1.3", webSocketDebuggerUrl: "ws://127.0.0.1:50001/devtools/browser/id",
  }) }) });
  assert.strictEqual(result.ok, true);
  assert.deepStrictEqual(phases, ["incognito_cdp_launch_started", "incognito_cdp_ready"]);
  const persistentScript = powershellScript("persistent");
  assert(persistentScript.includes("WASM-Agent\\browser\\cdp-persistent"));
  assert(!persistentScript.includes("--incognito"));
  assert(!persistentScript.includes("Remove-Item -LiteralPath '$profile'"));
  console.log("windows private CDP tests: PASS");
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
