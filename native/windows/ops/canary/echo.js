"use strict";

async function run(context) {
  const version = context?.operation?.version || "20260612T0000";
  return {
    ok: true,
    stable: true,
    operation: "canary_echo",
    source: "hot_operation",
    message: "hot op loaded",
    version,
    dryRun: Boolean(context?.dryRun),
    failureClassification: "pass",
    nextAction: "Run Hermes wake proof after shell self-test passes.",
  };
}

module.exports = { run };
