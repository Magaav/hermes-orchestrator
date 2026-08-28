"use strict";

const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { EventEmitter } = require("events");
const { installAppLifecycle } = require("./app-lifecycle");

function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-app-lifecycle-"));
  const app = new EventEmitter();
  const processRef = new EventEmitter();
  processRef.platform = "win32";
  const calls = [];
  Object.assign(app, {
    relaunch: () => calls.push("relaunch"),
    exit: (code) => calls.push(`exit:${code}`),
    quit: () => calls.push("quit"),
  });
  const timers = [];
  installAppLifecycle({
    app,
    processRef,
    flushAuthCookies: ({ reason }) => calls.push(`flush:${reason}`),
    fatalLogPath: path.join(root, "fatal.log"),
    recoveryStatePath: path.join(root, "recovery.json"),
    now: () => 1_000,
    setTimer: (callback) => { timers.push(callback); return { unref() {} }; },
  });
  return { app, processRef, calls, timers, root };
}

{
  const f = fixture();
  f.processRef.emit("uncaughtException", new Error("boom"), "uncaughtException");
  assert.deepStrictEqual(f.calls, []);
  assert.strictEqual(f.timers.length, 1);
  f.timers[0]();
  assert.deepStrictEqual(f.calls, ["relaunch", "exit:1"]);
  assert.match(fs.readFileSync(path.join(f.root, "fatal.log"), "utf8"), /main-process-recovery-scheduled/);
}

{
  const f = fixture();
  f.app.emit("before-quit");
  f.app.emit("window-all-closed");
  assert.deepStrictEqual(f.calls, ["flush:before_quit", "quit"]);
}

{
  const f = fixture();
  fs.writeFileSync(path.join(f.root, "recovery.json"), JSON.stringify({ windowStartedAtMs: 1_000, relaunchCount: 2 }));
  f.processRef.emit("uncaughtException", new Error("repeat"), "uncaughtException");
  assert.strictEqual(f.timers.length, 0);
  assert.match(fs.readFileSync(path.join(f.root, "fatal.log"), "utf8"), /crash_loop_breaker/);
}

console.log("app lifecycle tests passed");
