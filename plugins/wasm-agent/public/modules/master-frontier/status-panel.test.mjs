import assert from "node:assert/strict";
import test from "node:test";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./status-panel.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const {
  masterFrontierReasoningEffort,
  masterFrontierRequestPreferences,
  masterFrontierStatusModel,
  mergeMasterFrontierStatusUsage,
  mergeMasterFrontierSessionStatusDiagnostics,
  setMasterFrontierReasoningEffort,
} = await import(moduleUrl);

test("reasoning preference defaults to light and is hot configurable", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value),
  };
  assert.equal(masterFrontierReasoningEffort(storage), "low");
  assert.deepEqual(masterFrontierRequestPreferences(storage), { reasoning_effort: "low", text_verbosity: "low" });
  assert.equal(setMasterFrontierReasoningEffort("xhigh", storage), "xhigh");
  assert.equal(masterFrontierReasoningEffort(storage), "xhigh");
  assert.equal(setMasterFrontierReasoningEffort("unsupported", storage), "low");
});

test("status reports the effective reasoning effort", () => {
  const model = masterFrontierStatusModel({ diagnostics: { reasoning_effort: "high" }, reasoningEffort: "xhigh" });
  assert.equal(model.reasoningEffort, "xhigh");
  assert.equal(model.effectiveReasoningEffort, "high");
});

test("status uses the product dropdown component", () => {
  assert.match(source, /element\(document, "s-select", "codex-status__reasoning"\)/);
  assert.doesNotMatch(source, /element\(document, "select", "codex-status__reasoning"\)/);
});

test("builds exact Codex-style context and weekly status from diagnostics", () => {
  const model = masterFrontierStatusModel({
    sessionId: "019fd3b2-6b1e-7b50-bd8e-f4dcfc2d87d8",
    diagnostics: {
      model: "gpt-5.6-luna",
      status_telemetry: {
        model: { value: "gpt-5.6-luna" },
        context_window: { tokens: 258000 },
        seven_day: { status: "reported" },
      },
      context_window_tokens: 258000,
      context: [{ provider_usage: { prompt_tokens: 205703 } }],
      rate_limits: { seven_day: { percent_left: 39, resets_at_label: "Aug 12" } },
    },
  });
  assert.equal(model.contextUsed, 205703);
  assert.equal(model.modelName, "gpt-5.6-luna");
  assert.equal(model.contextLeft, 20);
  assert.equal(model.weeklyLeft, 39);
  assert.equal(model.weeklyReset, "Aug 12");
});

test("prefers the latest active prompt over cumulative session usage", () => {
  const model = masterFrontierStatusModel({
    diagnostics: {
      context: [{ provider_usage: { prompt_tokens: 11372 } }],
      token_usage_total: { input_tokens: 55610 },
    },
    sessionSummary: {
      turns: 4,
      usage: { input_tokens: 55610, cached_input_tokens: 32000, output_tokens: 900, total_tokens: 56510 },
    },
  });
  assert.equal(model.contextUsed, 11372);
  assert.equal(model.sessionTokens, 56510);
  assert.equal(model.sessionFresh, 23610);
  assert.equal(model.sessionCached, 32000);
  assert.equal(model.sessionTurns, 4);
});

test("does not invent unavailable provider limits", () => {
  const model = masterFrontierStatusModel({ diagnostics: {
    token_usage: { input_tokens: 0 },
    token_usage_total: { input_tokens: 32590 },
  } });
  assert.equal(model.contextUsed, 32590);
  assert.equal(model.contextWindow, null);
  assert.equal(model.weeklyLeft, null);
  assert.equal(model.weeklyStatus, "unknown");
});

test("distinguishes an optional weekly limit omitted by the provider", () => {
  const model = masterFrontierStatusModel({ diagnostics: {
    token_usage_total: {
      input_tokens: 1200,
      status_telemetry: {
        model: { value: "gpt-5.6-luna" },
        context_window: { tokens: 258400 },
        seven_day: { status: "provider_omitted" },
      },
    },
  } });
  assert.equal(model.modelName, "gpt-5.6-luna");
  assert.equal(model.contextWindow, 258400);
  assert.equal(model.weeklyStatus, "provider_omitted");
});

test("cost-ledger refresh preserves provider status metadata", () => {
  const merged = mergeMasterFrontierStatusUsage(
    { input_tokens: 200000 },
    {
      model: "gpt-5.6-luna", context_window_tokens: 258400,
      rate_limits: { seven_day: { percent_left: 37 } },
      status_telemetry: { seven_day: { status: "reported" } },
    },
  );
  assert.equal(merged.input_tokens, 200000);
  assert.equal(merged.model, "gpt-5.6-luna");
  assert.equal(merged.context_window_tokens, 258400);
  assert.equal(merged.rate_limits.seven_day.percent_left, 37);
  assert.equal(merged.status_telemetry.seven_day.status, "reported");
});

test("an incomplete later turn carries forward provider-reported session telemetry", () => {
  const diagnostics = mergeMasterFrontierSessionStatusDiagnostics(
    { token_usage_total: { active_context_tokens: 16194, input_tokens: 31917 } },
    [{ diagnostics: {
      token_usage_total: {
        context_window_tokens: 258400,
        rate_limits: { seven_day: { percent_left: 92, resets_at: 1787853220 } },
        status_telemetry: { context_window: { status: "reported", tokens: 258400 }, seven_day: { status: "reported" } },
      },
    } }],
  );
  const model = masterFrontierStatusModel({ diagnostics });
  assert.equal(model.contextUsed, 16194);
  assert.equal(model.contextWindow, 258400);
  assert.equal(model.weeklyLeft, 92);
  assert.equal(model.weeklyStatus, "reported");
});
