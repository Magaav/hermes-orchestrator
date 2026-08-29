"use strict";

const fs = require("fs");
const path = require("path");

const CRASH_WINDOW_MS = 60_000;
const MAX_RELAUNCHES_PER_WINDOW = 2;

function errorDetails(error) {
  return {
    name: String(error?.name || "Error"),
    message: String(error?.message || error || "unknown_main_process_error"),
    stack: String(error?.stack || "").slice(0, 16_384),
  };
}

function appendEvent(filePath, event) {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.appendFileSync(filePath, `${JSON.stringify(event)}\n`);
  } catch {
    // Fault reporting must never become a second fatal error.
  }
}

function readRecoveryState(filePath) {
  try { return JSON.parse(fs.readFileSync(filePath, "utf8")); }
  catch { return { windowStartedAtMs: 0, relaunchCount: 0 }; }
}

function writeRecoveryState(filePath, state) {
  try {
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, `${JSON.stringify(state)}\n`);
  } catch {
    // The in-memory recovery path still works when persistence is unavailable.
  }
}

function installAppLifecycle({ app, processRef = process, flushAuthCookies, fatalLogPath, recoveryStatePath, now = Date.now, setTimer = setTimeout } = {}) {
  let recoveryScheduled = false;

  const record = (kind, error, extra = {}) => appendEvent(fatalLogPath, {
    timestamp: new Date(now()).toISOString(),
    kind,
    ...errorDetails(error),
    ...extra,
  });

  const recover = (error, origin) => {
    if (recoveryScheduled) {
      record("main-process-recovery-coalesced", error, { origin });
      return;
    }
    const currentTime = now();
    const previous = readRecoveryState(recoveryStatePath);
    const withinWindow = currentTime - Number(previous.windowStartedAtMs || 0) <= CRASH_WINDOW_MS;
    const state = {
      windowStartedAtMs: withinWindow ? Number(previous.windowStartedAtMs) : currentTime,
      relaunchCount: withinWindow ? Number(previous.relaunchCount || 0) : 0,
    };
    if (state.relaunchCount >= MAX_RELAUNCHES_PER_WINDOW) {
      record("main-process-recovery-suppressed", error, { origin, reason: "crash_loop_breaker", ...state });
      return;
    }
    state.relaunchCount += 1;
    writeRecoveryState(recoveryStatePath, state);
    recoveryScheduled = true;
    record("main-process-recovery-scheduled", error, { origin, ...state });
    const timer = setTimer(() => {
      try {
        app.relaunch();
        app.exit(1);
      } catch (relaunchError) {
        recoveryScheduled = false;
        record("main-process-relaunch-failed", relaunchError, { origin });
      }
    }, 250);
    timer?.unref?.();
  };

  processRef.on("uncaughtException", (error, origin) => recover(error, String(origin || "uncaughtException")));
  processRef.on("unhandledRejection", (reason) => record("main-process-unhandled-rejection", reason));
  app.on("before-quit", () => {
    void flushAuthCookies({ reason: "before_quit" });
  });
  app.on("window-all-closed", () => {
    if (processRef.platform !== "darwin") app.quit();
  });

  return { recover };
}

module.exports = { installAppLifecycle };
