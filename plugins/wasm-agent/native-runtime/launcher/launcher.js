"use strict";

const runtimeStatus = {
  schema: "hermes.wasm_agent.downloaded_runtime.launcher.v1",
  runtimeId: "native-launcher-runtime",
  loadedAt: new Date().toISOString(),
  source: "downloaded-runtime",
  updateMode: "release-feed",
};

window.__wasmAgentNativeDownloadedRuntime = runtimeStatus;

const target = document.getElementById("native-runtime-status");
if (target) target.textContent = JSON.stringify(runtimeStatus, null, 2);
