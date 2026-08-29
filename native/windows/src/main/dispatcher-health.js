"use strict";

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const SCHEMA = "hermes.wasm_agent.windows_dispatcher_lease.v1";
const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_TIMEOUT_MS = 240_000;
const UPLOAD_TIMEOUT_MS = 15_000;

function defaultStatePath() {
  const root = process.env.WASM_AGENT_SUPERVISOR_STATE_DIR || path.join(process.env.LOCALAPPDATA || path.join(os.homedir(), "AppData", "Local"), "WASM Agent Native", "supervisor");
  return path.join(root, "dispatcher-lease.json");
}

function atomicWrite(target, payload) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(payload)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, target);
}

function timeoutFor(command = {}) {
  const payload = command?.payload && typeof command.payload === "object" ? command.payload : {};
  const requested = Number(payload.nativeControlTimeoutMs || payload.native_control_timeout_ms || payload.commandTimeoutMs || payload.command_timeout_ms || 0);
  if (Number.isFinite(requested) && requested > 0) return Math.max(1000, Math.min(requested, MAX_TIMEOUT_MS));
  const type = String(command.type || "");
  if (type === "run_hot_operation") {
    const hot = Number(payload.timeoutMs || payload.timeout_ms || payload.args?.timeoutMs || payload.args?.timeout_ms || 0);
    return Number.isFinite(hot) && hot > 0 ? Math.max(1000, Math.min(hot + 15_000, MAX_TIMEOUT_MS)) : 75_000;
  }
  if (type === "windows_shell_execute_unrestricted") {
    const shell = Number(payload.timeoutMs || payload.timeout_ms || 0);
    if (Number.isFinite(shell) && shell > 0) return Math.max(1000, Math.min(shell + 5_000, MAX_TIMEOUT_MS));
  }
  if (type === "run_shell_self_test") return 10_000;
  return DEFAULT_TIMEOUT_MS;
}

function createDispatcherHealth({ statePath = defaultStatePath(), now = () => Date.now(), setTimer = setTimeout, clearTimer = clearTimeout, audit = () => {}, recentLogs = () => [] } = {}) {
  const write = (command, phase, timeoutMs, extra = {}) => {
    const started = now();
    atomicWrite(statePath, { schema: SCHEMA, active: phase !== "finished", commandId: String(command?.id || "unknown"), commandType: String(command?.type || "unknown"), phase, pid: process.pid, updatedAt: new Date(started).toISOString(), deadlineAt: new Date(started + timeoutMs).toISOString(), ...extra });
  };
  const timeoutResult = (command, timeoutMs, startedAt) => ({ ok: false, operation: String(command?.type || "unknown"), error: "handler_timeout", failureClassification: "handler_timeout", started_at: startedAt, completed_at: new Date(now()).toISOString(), timedOut: true, timeoutMs, message: `Native-control handler timed out after ${timeoutMs}ms.`, logsTail: recentLogs() });
  return {
    markUploading(command) { write(command, "uploading", UPLOAD_TIMEOUT_MS); },
    markFinished(command, upload = {}) { write(command, "finished", 0, { uploadOk: upload?.ok === true }); },
    async execute(command, handler) {
      const timeoutMs = timeoutFor(command); const startedAt = new Date(now()).toISOString();
      write(command, "handling", timeoutMs);
      let handle; let timedOut = false;
      const work = Promise.resolve().then(() => handler(command));
      work.catch((error) => { if (timedOut) audit({ action: "command_late_rejection_after_timeout", id: command?.id || "", type: command?.type || "", error: String(error?.message || error) }); });
      const timeout = new Promise((resolve) => { handle = setTimer(() => { timedOut = true; const result = timeoutResult(command, timeoutMs, startedAt); audit({ action: "command_timeout", id: command?.id || "", type: command?.type || "", timeoutMs, result }); resolve(result); }, timeoutMs); handle?.unref?.(); });
      const result = await Promise.race([work, timeout]);
      if (handle) clearTimer(handle);
      write(command, "handler_finished", UPLOAD_TIMEOUT_MS, { handlerOk: result?.ok === true });
      return result && typeof result === "object" ? result : { ok: false, error: "result_seen_wrong_shape", failureClassification: "result_seen_wrong_shape", rawResult: result };
    },
  };
}

module.exports = { DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS, SCHEMA, UPLOAD_TIMEOUT_MS, createDispatcherHealth, defaultStatePath, timeoutFor };
