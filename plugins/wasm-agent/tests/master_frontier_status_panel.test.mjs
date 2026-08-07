import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const source = await readFile(new URL("../public/modules/master-frontier/status-panel.js", import.meta.url), "utf8");
const module = await import(`data:text/javascript,${encodeURIComponent(source)}`);

const merged = module.mergeMasterFrontierStatusUsage(
  { input_tokens: 12_000, context_window_tokens: 258_000 },
  { input_tokens: 145_635, active_context_tokens: 12_004, context_window_tokens: 258_000 },
);
const model = module.masterFrontierStatusModel({ diagnostics: { token_usage_total: merged } });

assert.equal(merged.input_tokens, 12_000);
assert.equal(merged.active_context_tokens, 12_004);
assert.equal(model.contextUsed, 12_004);
assert.equal(model.contextWindow, 258_000);

const calls = [];
const selected = await module.refreshMasterFrontierStatus({
  messages: [{ run_id: "old" }, { content: "no run" }, { run_id: "latest" }],
  refreshLedger: async (message) => {
    calls.push(message.run_id);
    return message.run_id;
  },
});
assert.equal(selected.message.run_id, "latest");
assert.equal(selected.result, "latest");
assert.deepEqual(calls, ["latest"]);
