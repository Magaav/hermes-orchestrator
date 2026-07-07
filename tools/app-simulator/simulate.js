#!/usr/bin/env node
"use strict";

function usage() {
  console.log(`horc app simulator

Usage:
  node tools/app-simulator/simulate.js web [--avatar-quest]
  node tools/app-simulator/simulate.js android [--device|--emulator|--local-report PATH|--voice-wake FIXTURE]
  node tools/app-simulator/simulate.js windows
  node tools/app-simulator/simulate.js all

Environment:
  WASM_AGENT_SIM_URL       Override the web target URL.
  WASM_AGENT_SIM_CHROMIUM  Override Chromium/Chrome executable path.
  WASM_AGENT_SIM_HEADED=1  Run the browser headed.
  WASM_AGENT_SIM_ADB       Override adb executable path.
  WASM_AGENT_ANDROID_APK   Override Android APK path.
  WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS
                            Wait for manual Google authorization proof.
  WASM_AGENT_SIM_ANDROID_VOICE_WAKE
                            Voice wake fixture name for --voice-wake.
`);
}

function parseAndroidArgs(args) {
  const options = {
    backend: "auto",
    localReportPath: "",
    interactiveOAuth: false,
    oauthWaitMs: null,
    voiceWakeFixture: "",
  };
  for (let index = 0; index < args.length; index += 1) {
    const arg = args[index];
    if (arg === "--device") {
      options.backend = "device";
    } else if (arg === "--emulator") {
      options.backend = "emulator";
    } else if (arg === "--local-report") {
      const value = args[index + 1] || "";
      if (!value || value.startsWith("--")) throw new Error("--local-report requires a path");
      options.backend = "local-report";
      options.localReportPath = value;
      index += 1;
    } else if (arg.startsWith("--local-report=")) {
      options.backend = "local-report";
      options.localReportPath = arg.slice("--local-report=".length);
    } else if (arg === "--interactive-oauth") {
      options.interactiveOAuth = true;
      options.oauthWaitMs = Number(process.env.WASM_AGENT_SIM_ANDROID_OAUTH_WAIT_MS || 180000);
    } else if (arg === "--voice-wake") {
      const value = args[index + 1] || "";
      if (!value || value.startsWith("--")) throw new Error("--voice-wake requires a fixture name");
      options.voiceWakeFixture = value;
      index += 1;
    } else if (arg.startsWith("--voice-wake=")) {
      options.voiceWakeFixture = arg.slice("--voice-wake=".length);
    } else if (arg.startsWith("--oauth-wait-ms=")) {
      options.oauthWaitMs = Number(arg.slice("--oauth-wait-ms=".length));
    } else {
      throw new Error(`unknown android simulator option: ${arg}`);
    }
  }
  return options;
}

function parseWebArgs(args) {
  const options = {
    avatarQuest: false,
  };
  for (const arg of args) {
    if (arg === "--avatar-quest") {
      options.avatarQuest = true;
    } else {
      throw new Error(`unknown web simulator option: ${arg}`);
    }
  }
  return options;
}

function commandLabel(target, args) {
  return `horc simulate ${target}${args.length ? ` ${args.join(" ")}` : ""}`;
}

async function main() {
  const target = process.argv[2] || "help";
  const args = process.argv.slice(3);
  if (target === "help" || target === "-h" || target === "--help") {
    usage();
    return;
  }

  if (target === "web") {
    const options = parseWebArgs(args);
    const { runAvatarQuestSimulation, runWebSimulation } = require("./web");
    const result = options.avatarQuest
      ? await runAvatarQuestSimulation({ command: commandLabel("web", args) })
      : await runWebSimulation({ command: commandLabel("web", args) });
    process.exitCode = result.status === "passed" ? 0 : 1;
    return;
  }

  if (target === "android") {
    const { runAndroidSimulation } = require("./android");
    const result = await runAndroidSimulation({ command: commandLabel("android", args), ...parseAndroidArgs(args) });
    process.exitCode = result.status === "failed" ? 1 : 0;
    return;
  }

  if (target === "windows") {
    const { runPendingSimulation } = require("./skeleton");
    await runPendingSimulation(target, { command: commandLabel(target, args) });
    process.exitCode = 0;
    return;
  }

  if (target === "all") {
    const { runPendingSimulation } = require("./skeleton");
    const { runAndroidSimulation } = require("./android");
    const { runWebSimulation } = require("./web");
    const results = [];
    results.push(await runWebSimulation({ command: commandLabel("all", args) }));
    results.push(await runAndroidSimulation({ command: commandLabel("all", args) }));
    results.push(await runPendingSimulation("windows", { command: "horc simulate all" }));
    console.log("horc simulate all:");
    for (const result of results) {
      const score = result.score == null ? "n/a" : `${result.score}/100`;
      console.log(`  ${result.platform}: ${result.status} (${score})`);
    }
    process.exitCode = results.some((result) => result.status === "failed") ? 1 : 0;
    return;
  }

  console.error(`unknown simulator target: ${target}`);
  usage();
  process.exitCode = 2;
}

main().catch((error) => {
  console.error(error?.stack || error?.message || String(error));
  process.exitCode = 1;
});
