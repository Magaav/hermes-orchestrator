"use strict";
const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { createDispatcherHealth, timeoutFor } = require("./dispatcher-health");

const root = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-dispatcher-health-"));
const statePath = path.join(root, "dispatcher-lease.json");
let clock = Date.parse("2026-08-28T00:00:00Z"); let timer;
const health = createDispatcherHealth({ statePath, now: () => clock, setTimer: (fn) => { timer = fn; return { unref() {} }; }, clearTimer: () => {} });
assert.strictEqual(timeoutFor({ type: "run_shell_self_test" }), 10_000);
assert.strictEqual(timeoutFor({ type: "run_hot_operation", payload: { args: { timeout_ms: 180_000 } } }), 195_000);
(async () => {
  const pending = health.execute({ id: "cmd-stuck", type: "get_bridge_status" }, () => new Promise(() => {}));
  let lease = JSON.parse(fs.readFileSync(statePath)); assert.strictEqual(lease.phase, "handling"); assert.strictEqual(lease.active, true);
  clock += 60_000; timer(); const result = await pending; assert.strictEqual(result.failureClassification, "handler_timeout");
  lease = JSON.parse(fs.readFileSync(statePath)); assert.strictEqual(lease.phase, "handler_finished");
  health.markUploading({ id: "cmd-stuck", type: "get_bridge_status" }); assert.strictEqual(JSON.parse(fs.readFileSync(statePath)).phase, "uploading");
  health.markFinished({ id: "cmd-stuck", type: "get_bridge_status" }, { ok: true }); lease = JSON.parse(fs.readFileSync(statePath)); assert.strictEqual(lease.active, false); assert.strictEqual(lease.uploadOk, true);
  fs.rmSync(root, { recursive: true, force: true }); console.log("dispatcher health tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
