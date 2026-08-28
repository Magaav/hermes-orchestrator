"use strict";

const assert = require("assert");
const { createWindowsNativeCommands } = require("./windows-native-commands");

(async () => {
  const calls = [];
  const commands = createWindowsNativeCommands({
    companion: () => ({ show: () => ({ ok: true, state: "visible" }) }),
    desktop: {
      operations: ["windows_desktop_inspect"],
      control: {
        runNotepadCanary: async () => ({ ok: true, canary: true }),
        execute: async (type, payload, id) => { calls.push({ type, payload, id }); return { ok: true }; },
      },
    },
  });
  assert(commands.operations.includes("show_companion_overlay") && commands.operations.includes("windows_desktop_inspect"));
  assert.strictEqual((await commands.execute("show_companion_overlay")).result.state, "visible");
  assert.strictEqual((await commands.execute("windows_desktop_inspect", { max_elements: 2 }, "cmd-1")).handled, true);
  assert.deepStrictEqual(calls, [{ type: "windows_desktop_inspect", payload: { max_elements: 2 }, id: "cmd-1" }]);
  assert.strictEqual((await commands.execute("unknown")).handled, false);
  console.log("Windows native command dispatcher tests passed");
})().catch((error) => { console.error(error); process.exitCode = 1; });
