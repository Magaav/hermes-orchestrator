import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./status-panel.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { masterFrontierStatusModel, mergeMasterFrontierStatusUsage } = await import(moduleUrl);

test("builds exact Codex-style context and weekly status from diagnostics", () => {
  const model = masterFrontierStatusModel({
    sessionId: "019fd3b2-6b1e-7b50-bd8e-f4dcfc2d87d8",
    diagnostics: {
      context_window_tokens: 258000,
      context: [{ provider_usage: { prompt_tokens: 205703 } }],
      rate_limits: { seven_day: { percent_left: 39, resets_at_label: "Aug 12" } },
    },
  });
  assert.equal(model.contextUsed, 205703);
  assert.equal(model.contextLeft, 20);
  assert.equal(model.weeklyLeft, 39);
  assert.equal(model.weeklyReset, "Aug 12");
});

test("prefers the latest active prompt over cumulative session usage", () => {
  const model = masterFrontierStatusModel({ diagnostics: {
    context: [{ provider_usage: { prompt_tokens: 11372 } }],
    token_usage_total: { input_tokens: 55610 },
  } });
  assert.equal(model.contextUsed, 11372);
});

test("does not invent unavailable provider limits", () => {
  const model = masterFrontierStatusModel({ diagnostics: {
    token_usage: { input_tokens: 0 },
    token_usage_total: { input_tokens: 32590 },
  } });
  assert.equal(model.contextUsed, 32590);
  assert.equal(model.contextWindow, null);
  assert.equal(model.weeklyLeft, null);
});

test("cost-ledger refresh preserves provider status metadata", () => {
  const merged = mergeMasterFrontierStatusUsage(
    { input_tokens: 200000 },
    { context_window_tokens: 258400, rate_limits: { seven_day: { percent_left: 37 } } },
  );
  assert.equal(merged.input_tokens, 200000);
  assert.equal(merged.context_window_tokens, 258400);
  assert.equal(merged.rate_limits.seven_day.percent_left, 37);
});
