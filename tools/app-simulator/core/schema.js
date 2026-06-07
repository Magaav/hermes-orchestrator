"use strict";

const LIFECYCLE_PHASES = [
  "boot",
  "observe",
  "act",
  "assert",
  "collect evidence",
  "score",
  "report",
];

function isoTimestamp() {
  return new Date().toISOString();
}

function runId(prefix = "sim") {
  return `${prefix}-${isoTimestamp().replace(/[-:.]/g, "").replace("T", "T").replace("Z", "Z")}`;
}

function createResult({ platform, command, engine = null }) {
  return {
    schema: "hermes.app_simulator.result.v1",
    runId: runId(platform || "sim"),
    platform,
    command,
    status: "running",
    score: null,
    startedAt: isoTimestamp(),
    finishedAt: null,
    lifecycle: LIFECYCLE_PHASES.map((phase) => ({
      phase,
      status: "pending",
      startedAt: null,
      finishedAt: null,
      detail: "",
    })),
    engine,
    target: {},
    guardrails: [
      "Web simulation verifies PWA/browser behavior only.",
      "Android APK behavior is verified only by horc simulate android with a connected adb device and a passing report.",
      "Windows installed-app behavior is not verified until horc simulate windows exists and passes.",
      "Build success is not runtime verification.",
    ],
    assertions: [],
    evidence: {
      artifacts: {},
      console: [],
      networkFailures: [],
      diagnostics: [],
      observations: {},
    },
    errors: [],
    pendingReason: "",
  };
}

module.exports = {
  LIFECYCLE_PHASES,
  createResult,
  isoTimestamp,
};
