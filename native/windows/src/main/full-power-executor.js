const { spawn: spawnProcess } = require("child_process");

const RESULT_SCHEMA = "hermes.wasm_agent.windows_full_power_execution.v1";
const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_TIMEOUT_MS = 240_000;
const MAX_OUTPUT_BYTES = 512 * 1024;

function boundedText(chunks, maxBytes = MAX_OUTPUT_BYTES) {
  const value = Buffer.concat(chunks).toString("utf8");
  if (Buffer.byteLength(value) <= maxBytes) return { text: value, truncated: false };
  const tail = Buffer.from(value).subarray(-maxBytes).toString("utf8");
  return { text: tail, truncated: true };
}

function normalizedTimeout(value) {
  const parsed = Number(value || DEFAULT_TIMEOUT_MS);
  if (!Number.isFinite(parsed)) return DEFAULT_TIMEOUT_MS;
  return Math.max(1_000, Math.min(Math.round(parsed), MAX_TIMEOUT_MS));
}

function invocation(payload = {}, platform = process.platform) {
  const command = String(payload.command || "");
  if (!command.trim()) throw new Error("full_power_command_missing");
  const shell = String(payload.shell || "powershell").trim().toLowerCase();
  if (platform === "win32") {
    if (shell === "cmd") return { file: "cmd.exe", args: ["/d", "/s", "/c", command], shell };
    if (shell === "powershell") return { file: "powershell.exe", args: ["-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", command], shell };
    throw new Error("full_power_shell_invalid");
  }
  if (shell !== "sh" && shell !== "powershell" && shell !== "cmd") throw new Error("full_power_shell_invalid");
  return { file: "/bin/sh", args: ["-lc", command], shell: "sh" };
}

function createFullPowerExecutor({ spawn = spawnProcess, platform = process.platform, now = Date.now, baseEnv = process.env } = {}) {
  async function execute(payload = {}, commandId = "") {
    const spec = invocation(payload, platform);
    const timeoutMs = normalizedTimeout(payload.timeout_ms ?? payload.timeoutMs);
    const cwd = String(payload.cwd || "").trim() || undefined;
    const overrides = payload.environment && typeof payload.environment === "object" && !Array.isArray(payload.environment)
      ? Object.fromEntries(Object.entries(payload.environment).map(([key, value]) => [String(key), String(value)]))
      : {};
    const startedMs = now();
    return await new Promise((resolve) => {
      const stdout = [];
      const stderr = [];
      let settled = false;
      let timedOut = false;
      let timer = null;
      let child;
      const finish = (exitCode, signal, error = "") => {
        if (settled) return;
        settled = true;
        if (timer) clearTimeout(timer);
        const out = boundedText(stdout);
        const err = boundedText(stderr);
        resolve({
          schema: RESULT_SCHEMA,
          ok: !timedOut && !error && exitCode === 0,
          command_id: String(commandId || ""),
          shell: spec.shell,
          exit_code: Number.isInteger(exitCode) ? exitCode : null,
          signal: String(signal || ""),
          timed_out: timedOut,
          timeout_ms: timeoutMs,
          duration_ms: Math.max(0, now() - startedMs),
          stdout: out.text,
          stderr: err.text,
          stdout_truncated: out.truncated,
          stderr_truncated: err.truncated,
          error: String(error || ""),
          inherited_process_token: true,
        });
      };
      try {
        child = spawn(spec.file, spec.args, {
          cwd,
          env: { ...baseEnv, ...overrides },
          windowsHide: true,
          stdio: ["ignore", "pipe", "pipe"],
        });
      } catch (error) {
        finish(null, "", error?.message || error);
        return;
      }
      child.stdout?.on("data", (chunk) => stdout.push(Buffer.from(chunk)));
      child.stderr?.on("data", (chunk) => stderr.push(Buffer.from(chunk)));
      child.once("error", (error) => finish(null, "", error?.message || error));
      child.once("close", (code, signal) => finish(code, signal));
      timer = setTimeout(() => {
        timedOut = true;
        child.kill("SIGTERM");
      }, timeoutMs);
      timer.unref?.();
    });
  }
  return { execute };
}

module.exports = { RESULT_SCHEMA, createFullPowerExecutor, invocation, normalizedTimeout };
