"use strict";

const assert = require("node:assert");
const { MAX_WINDOWS, normalizeInventory, powershellScript, run } = require("./windows-open-apps");

const bounded = normalizeInventory({
  windows: Array.from({ length: MAX_WINDOWS + 3 }, (_, index) => ({
    title: ` App ${index} `, processName: `proc${index}`, processId: index + 1,
    windowHandle: `0x${index.toString(16)}`, visible: true, minimized: index === 1,
  })),
});
assert.strictEqual(bounded.windowCount, MAX_WINDOWS);
assert.strictEqual(bounded.truncated, true);
assert.strictEqual(bounded.windows[0].title, "App 0");
assert.strictEqual(bounded.windows[1].minimized, true);
assert.deepStrictEqual(bounded.proof, ["windows.desktop.top_level_windows"]);

const script = powershellScript();
assert(script.includes("EnumWindows"));
assert(script.includes("IsWindowVisible"));
assert(script.includes("IsIconic"));
assert(script.includes(`Select-Object -First ${MAX_WINDOWS}`));
assert(!script.includes("context.args"));

(async () => {
  const phases = [];
  const result = await run({ markPhase: (phase) => phases.push(phase) }, {
    platform: "win32",
    executeInventory: async () => ({ ok: true, stdout: JSON.stringify({ windows: [
      { title: "WASM Agent", processName: "WASM Agent", processId: 12, windowHandle: "0x10", visible: true, minimized: false },
      { title: "notes.txt - Notepad", processName: "Notepad", processId: 44, windowHandle: "0x20", visible: true, minimized: true },
    ], truncated: false }) }),
  });
  assert.strictEqual(result.ok, true);
  assert.strictEqual(result.windowCount, 2);
  assert.strictEqual(result.windows[1].processName, "Notepad");
  assert.deepStrictEqual(phases, ["top_level_window_inventory_started", "top_level_window_inventory_complete"]);
  console.log("windows open apps tests: PASS");
})().catch((error) => { console.error(error.stack || error); process.exit(1); });
