const MASTER_FRONTIER_ENVELOPE_V2_TIMELINE_EVENT_TYPES = Object.freeze([
  "llm.inference.started",
  "llm.reason.summary",
  "semantic.decision",
  "command.proposed",
  "command.accepted",
  "command.rejected",
  "command.dispatched",
  "command.started",
  "evidence.received",
  "evidence.missing",
  "command.failed",
  "llm.inference.completed",
  "turn.usage.updated",
  "gate.started",
  "gate.decision",
  "answer.started",
  "answer.final",
  "loop_contract_violation",
]);

const MASTER_FRONTIER_LEGACY_TIMELINE_EVENT_TYPES = Object.freeze([
  "bridge.run.started",
  "bridge.run.completed",
  "backend.run.started",
  "backend.run.completed",
  "envelope.created",
  "head.started",
  "head.decision",
  "hermes.dispatch",
  "route.resolved",
  "route_contract_missing",
  "run.final",
  "run.started",
  "tokens.used",
]);

const MASTER_FRONTIER_TIMELINE_EVENT_TYPE_SET = new Set([
  ...MASTER_FRONTIER_ENVELOPE_V2_TIMELINE_EVENT_TYPES,
  ...MASTER_FRONTIER_LEGACY_TIMELINE_EVENT_TYPES,
]);

function cleanTimelineValue(value) {
  return String(value || "").trim().toLowerCase();
}

export function isMasterFrontierTimelineEventType(value) {
  const eventType = cleanTimelineValue(value);
  return MASTER_FRONTIER_TIMELINE_EVENT_TYPE_SET.has(eventType)
    || eventType.startsWith("files.")
    || eventType.startsWith("loop.")
    || eventType.startsWith("proof.")
    || eventType.startsWith("tests.");
}

export function isMasterFrontierTimelineAction(action = {}) {
  const label = cleanTimelineValue(action.label);
  const meta = cleanTimelineValue(action.meta);
  const id = cleanTimelineValue(action.id);
  const eventType = cleanTimelineValue(action.event_type);
  const topic = cleanTimelineValue(action.topic);
  const kind = cleanTimelineValue(action.kind);
  if (label === "bridge.run.poll" || id === "bridge_run_poll") return false;
  if (topic === "run-api" && ["tool", "trace", "policy"].includes(kind) && !eventType) return false;
  if (id === "tokens_used" || id === "bridge_token_usage") return true;
  if (isMasterFrontierTimelineEventType(eventType) || isMasterFrontierTimelineEventType(label)) return true;
  if (label.includes("file") || label.includes("files")) return true;
  if (label.includes("proof") || label.includes("test")) return true;
  if (meta.startsWith("tool.started") || meta.startsWith("tool.completed") || meta.startsWith("tool.finished")) return true;
  return false;
}
