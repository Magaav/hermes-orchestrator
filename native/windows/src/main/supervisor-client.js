const crypto = require("node:crypto");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawn } = require("node:child_process");

const SCHEMA = "hermes.wasm_agent.windows_supervisor.v1";

function supervisorStateRoot() {
  return path.join(process.env.WASM_AGENT_SUPERVISOR_STATE_DIR || path.join(os.homedir(), "AppData", "Local", "WASM Agent Native", "supervisor"));
}

function atomicWriteJson(target, payload) {
  fs.mkdirSync(path.dirname(target), { recursive: true });
  const temporary = `${target}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(payload, null, 2)}\n`, { mode: 0o600 });
  fs.renameSync(temporary, target);
}

function readJson(target) {
  try {
    return JSON.parse(fs.readFileSync(target, "utf8"));
  } catch {
    return null;
  }
}

function supervisorStatus() {
  const status = readJson(path.join(supervisorStateRoot(), "status.json"));
  const updateTimeline = readJson(path.join(supervisorStateRoot(), "update-timeline.json"));
  return status?.schema === SCHEMA
    ? { ...status, updateTimeline: updateTimeline?.schema === "hermes.wasm_agent.windows_update_timeline.v1" ? updateTimeline : null }
    : { schema: SCHEMA, ok: false, state: "unavailable", capabilities: [], updateTimeline: updateTimeline?.schema === "hermes.wasm_agent.windows_update_timeline.v1" ? updateTimeline : null };
}

async function requestSupervisorAction(type, payload = {}, options = {}) {
  const status = supervisorStatus();
  if (!status.ok) return { ok: false, error: "supervisor_unavailable", status };
  const id = `electron-${Date.now().toString(36)}-${crypto.randomBytes(5).toString("hex")}`;
  const root = supervisorStateRoot();
  const resultPath = path.join(root, "results", `${id}.json`);
  atomicWriteJson(path.join(root, "commands", `${id}.json`), { schema: SCHEMA, id, type, payload });
  const deadline = Date.now() + Math.max(500, Math.min(Number(options.timeoutMs || 5000), 15000));
  while (Date.now() < deadline) {
    const result = readJson(resultPath);
    if (result?.commandId === id) return result;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  return { ok: false, error: "supervisor_timeout", commandId: id };
}

async function activateOrLaunchInstaller(staged, latest = {}, validation = {}) {
  const status = supervisorStatus();
  if (status.ok && status.capabilities?.includes("update.activate")) {
    const result = await requestSupervisorAction("install_update", {
      installerPath: staged.path,
      sha256: latest.sha256 || validation.sha256,
      expectedBuildId: latest.buildId || "",
    });
    return result.ok ? { ok: true, supervised: true } : { ok: false, error: result.error || "supervisor_install_failed", supervisor: result };
  }
  try {
    spawn(staged.path, [], { detached: true, stdio: "ignore", windowsHide: false }).unref();
    return { ok: true, supervised: false };
  } catch (error) {
    return { ok: false, error: "installer_failed", message: String(error?.message || error) };
  }
}

module.exports = { SCHEMA, activateOrLaunchInstaller, requestSupervisorAction, supervisorStateRoot, supervisorStatus };
