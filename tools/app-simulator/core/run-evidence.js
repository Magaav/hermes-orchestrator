"use strict";

function evidenceToolNames(events) {
  return (Array.isArray(events) ? events : [])
    .filter((event) => event?.type === "evidence.received")
    .map((event) => String(event?.payload?.tool || ""))
    .filter(Boolean);
}

function runtimeInspectWasExecuted(events) {
  return (Array.isArray(events) ? events : []).some((event) => {
    const type = String(event?.type || "");
    const payload = event?.payload || {};
    const tool = String(payload.tool || payload.action?.tool || "");
    const code = String(payload.code || payload.result?.code || "");
    if (type === "command.started") {
      return tool === "inspect" || tool === "kernel.inspect" || String(event?.summary || "") === "kernel.inspect";
    }
    if (type === "evidence.received" || type === "command.failed") {
      return tool === "inspect" || tool === "kernel.inspect" || code === "runtime_action_entity_denied";
    }
    return false;
  });
}

module.exports = { evidenceToolNames, runtimeInspectWasExecuted };
