const assert = require("assert");
const { createObservabilityKernel, boundedLeaseMs } = require("./observability-kernel");

class FakeDebugger {
  constructor() { this.attached = false; this.listeners = new Map(); this.commands = []; }
  isAttached() { return this.attached; }
  attach() { this.attached = true; }
  detach() { this.attached = false; }
  on(name, fn) { this.listeners.set(name, fn); }
  removeListener(name) { this.listeners.delete(name); }
  async sendCommand(method) {
    this.commands.push(method);
    if (method === "Performance.getMetrics") return { metrics: [{ name: "Nodes", value: 12 }, { name: "Ignored", value: 99 }] };
    if (method === "Runtime.evaluate") return { result: { value: { route: "https://wa.colmeio.com/home", dom_nodes: 12 } } };
    return {};
  }
}

(async () => {
  let clock = 1_000;
  let expiry = null;
  const debug = new FakeDebugger();
  const win = { isDestroyed: () => false, webContents: { isDestroyed: () => false, debugger: debug } };
  const kernel = createObservabilityKernel({ now: () => clock, setTimer: (fn) => { expiry = fn; return { unref() {} }; }, clearTimer: () => {}, supervisorSnapshot: () => ({ updateTimeline: { phase: "installer_finished", expectedBuildId: "win-x64-test" } }) });
  assert.strictEqual(boundedLeaseMs(1), 5_000);
  assert.strictEqual(boundedLeaseMs(999_999), 120_000);
  const enabled = await kernel.execute(win, "observability_enable", { lease_ms: 10_000 });
  assert.strictEqual(enabled.active, true);
  assert.strictEqual(enabled.public_debug_port, false);
  assert.strictEqual(enabled.native_update.phase, "installer_finished");
  const collected = await kernel.execute(win, "observability_collect", { categories: ["analytics", "performance"] });
  assert.deepStrictEqual(collected.performance, { Nodes: 12 });
  assert.strictEqual(collected.analytics.dom_nodes, 12);
  await expiry();
  assert.strictEqual(kernel.status().active, false);
  assert.strictEqual(debug.attached, false);
  console.log("Electron observability kernel tests: PASS");
})().catch((error) => { console.error(error); process.exitCode = 1; });
