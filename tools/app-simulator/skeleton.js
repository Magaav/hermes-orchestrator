"use strict";

const { SimulationContext } = require("./core");

const FUTURE_ENGINES = {
  android: "Future engine: ADB + UIAutomator + optional Playwright Android/WebView.",
  windows: "Future engine: Playwright Electron + Windows smoke/PowerShell scripts.",
};

async function runPendingSimulation(platform, options = {}) {
  const ctx = new SimulationContext({
    platform,
    command: options.command || `horc simulate ${platform}`,
    engine: {
      name: "pending-skeleton",
      description: FUTURE_ENGINES[platform] || "Future simulator engine is not implemented yet.",
    },
  });

  ctx.startPhase("boot", "skeleton registered");
  ctx.completePhase("boot", "pending", FUTURE_ENGINES[platform]);
  for (const phase of ["observe", "act", "assert", "collect evidence", "score"]) {
    ctx.completePhase(phase, "pending", "Simulator engine pending.");
  }
  ctx.result.status = "pending";
  ctx.result.pendingReason = FUTURE_ENGINES[platform];
  ctx.result.assertions.push({
    name: `${platform} runtime verification`,
    status: "pending",
    detail: "No runtime behavior is verified by this skeleton.",
  });
  ctx.result.evidence.observations = {
    runtimeVerified: false,
    buildSuccessIsRuntimeVerification: false,
  };
  ctx.score();
  ctx.completePhase("report", "passed", "pending report written");
  ctx.report();

  console.log(`horc simulate ${platform}: pending`);
  console.log(`  ${FUTURE_ENGINES[platform]}`);
  console.log(`  report: ${ctx.reportDir}/summary.md`);
  return ctx.result;
}

module.exports = {
  FUTURE_ENGINES,
  runPendingSimulation,
};
