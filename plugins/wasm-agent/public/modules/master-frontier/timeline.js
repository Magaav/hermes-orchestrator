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
  "duplicate_action_repair_requested",
  "workflow_stage_action_rejected",
  "novelty_action_rejected",
  "action_completed_without_novelty",
  "no_semantic_progress",
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

function finiteCount(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.floor(number)) : null;
}

function compactCount(value) {
  const number = finiteCount(value);
  if (number === null) return "-";
  if (number < 1000) return String(number);
  if (number < 1_000_000) return `${(number / 1000).toFixed(number < 10_000 ? 1 : 0)}K`;
  return `${(number / 1_000_000).toFixed(number < 10_000_000 ? 1 : 0)}M`;
}

export function masterFrontierNewInputTokens(usage = {}) {
  const input = finiteCount(usage.input_tokens ?? usage.prompt_tokens);
  if (input === null) return null;
  return Math.max(0, input - (finiteCount(usage.cached_input_tokens) ?? 0));
}

export function masterFrontierDecisionCost(item = {}) {
  const eventType = cleanTimelineValue(item.event_type || item.label);
  if (eventType !== "turn.usage.updated") return null;
  const args = item.arguments && typeof item.arguments === "object" ? item.arguments : {};
  const context = args.context && typeof args.context === "object" ? args.context : args;
  const usage = context.provider_usage && typeof context.provider_usage === "object" ? context.provider_usage : {};
  const input = finiteCount(usage.prompt_tokens ?? usage.input_tokens);
  const cached = finiteCount(usage.cached_input_tokens) ?? 0;
  const output = finiteCount(usage.completion_tokens ?? usage.output_tokens);
  const decision = finiteCount(context.decision ?? args.decision);
  const fresh = masterFrontierNewInputTokens(usage);
  const projectionNew = finiteCount(context.new_chars);
  const projectionReused = finiteCount(context.repeated_chars);
  if (input === null && projectionNew === null && projectionReused === null) return null;
  const tokenParts = input === null ? [] : [
    `input ${compactCount(input)}`, `cached ${compactCount(cached)}`, `new ${compactCount(fresh)}`,
  ];
  if (output !== null) tokenParts.push(`out ${compactCount(output)}`);
  const projectionParts = [
    projectionNew === null ? "" : `new ${compactCount(projectionNew)} chars`,
    projectionReused === null ? "" : `reused ${compactCount(projectionReused)} chars`,
  ].filter(Boolean);
  return {
    decision,
    input_tokens: input,
    cached_input_tokens: cached,
    new_input_tokens: fresh,
    output_tokens: output,
    projection_new_chars: projectionNew,
    projection_repeated_chars: projectionReused,
    text: [decision === null ? "" : `decision ${decision}`, tokenParts.join(" · "), projectionParts.length ? `projection ${projectionParts.join(" / ")}` : ""].filter(Boolean).join(" · "),
  };
}

export function masterFrontierTimelineIcon(item = {}) {
  const label = cleanTimelineValue(item.label);
  const eventType = cleanTimelineValue(item.event_type);
  const status = cleanTimelineValue(item.status);
  if (status === "error") return "⚠️";
  if (status === "running") return "⏳";
  if (label === "run.started" || eventType === "run.started") return "▶️";
  if (label === "run.final" || eventType === "run.final" || eventType === "loop.finished" || label === "loop.finished") return "🏁";
  if (["loop.incomplete", "loop.blocked"].includes(eventType) || ["loop.incomplete", "loop.blocked"].includes(label)) return "⚠️";
  if (eventType.startsWith("loop.") || label.startsWith("loop.")) return "◈";
  if (label === "hermes.dispatch" || eventType === "hermes.dispatch") return "🪽";
  if (label === "tool.started" || eventType === "tool.started") return "🔧";
  if (label === "tool.finished" || eventType === "tool.finished") return "✓";
  if (label.includes("file") || eventType.startsWith("files.")) return "📄";
  if (label.includes("test") || eventType.startsWith("tests.")) return "🧪";
  if (label.includes("proof") || eventType.startsWith("proof.")) return "📋";
  if (label === "tokens.used" || eventType === "tokens.used" || eventType === "turn.usage.updated") return "🔶";
  return "•";
}
