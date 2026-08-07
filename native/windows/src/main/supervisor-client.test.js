const assert = require("node:assert");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const temporary = fs.mkdtempSync(path.join(os.tmpdir(), "wasm-agent-supervisor-client-"));
process.env.WASM_AGENT_SUPERVISOR_STATE_DIR = temporary;
const client = require("./supervisor-client");

assert.strictEqual(client.supervisorStatus().state, "unavailable");
fs.writeFileSync(path.join(temporary, "update-timeline.json"), JSON.stringify({ schema: "hermes.wasm_agent.windows_update_timeline.v1", phase: "installer_started", expectedBuildId: "win-x64-test" }));
assert.strictEqual(client.supervisorStatus().updateTimeline.phase, "installer_started");
fs.writeFileSync(path.join(temporary, "status.json"), JSON.stringify({ schema: client.SCHEMA, ok: true, state: "running", capabilities: ["update.activate"] }));
assert.strictEqual(client.supervisorStatus().state, "running");
assert.strictEqual(client.supervisorStatus().updateTimeline.expectedBuildId, "win-x64-test");

async function verifyCommandRoundTrip() {
  const watcher = setInterval(() => {
    const commandDir = path.join(temporary, "commands");
    if (!fs.existsSync(commandDir)) return;
    const filename = fs.readdirSync(commandDir).find((name) => name.endsWith(".json"));
    if (!filename) return;
    const command = JSON.parse(fs.readFileSync(path.join(commandDir, filename), "utf8"));
    assert.strictEqual(command.type, "install_update");
    fs.mkdirSync(path.join(temporary, "results"), { recursive: true });
    fs.writeFileSync(path.join(temporary, "results", `${command.id}.json`), JSON.stringify({ schema: client.SCHEMA, ok: true, commandId: command.id, action: command.type }));
    clearInterval(watcher);
  }, 10);
  const result = await client.requestSupervisorAction("install_update", { installerPath: "fixture.exe", sha256: "a".repeat(64) }, { timeoutMs: 1000 });
  assert.strictEqual(result.ok, true);
}

verifyCommandRoundTrip()
  .then(() => console.log("windows supervisor client tests passed"))
  .finally(() => fs.rmSync(temporary, { recursive: true, force: true }));
