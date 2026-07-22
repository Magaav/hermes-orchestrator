function cleanText(value, fallback = "") {
  const text = String(value ?? fallback).replace(/\s+/g, " ").trim();
  return text || fallback;
}

function clipped(value, limit) {
  const text = cleanText(value, "");
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3)).trim()}...`;
}

function boundedResumeCheckpoint(value = {}) {
  const candidates = [
    value?.resume_checkpoint,
    value?.diagnostic?.resume_checkpoint,
    value?.payload?.error?.resume_checkpoint,
    value?.payload?.resume_checkpoint,
  ];
  const checkpoint = candidates.find((item) => item && typeof item === "object" && !Array.isArray(item));
  const schema = cleanText(checkpoint?.schema);
  if (!checkpoint || !new Set([
    "master.frontier.v5.checkpoint.v1",
    "hermes.wasm_agent.restart_checkpoint.v1",
  ]).has(schema)) return null;
  try {
    const encoded = JSON.stringify(checkpoint);
    if (encoded.length > 24000) return null;
    if (schema === "master.frontier.v5.checkpoint.v1") {
      return {
        schema,
        protocol: cleanText(checkpoint.protocol || "v5"),
        scope: { source_run_id: cleanText(checkpoint?.scope?.source_run_id) },
        sha256: cleanText(checkpoint.sha256),
      };
    }
    return JSON.parse(encoded);
  } catch {
    return null;
  }
}

export function isAgentContinuationRequest(text = "") {
  const normalized = cleanText(text).toLowerCase().replace(/[.!?]+$/g, "").trim();
  return new Set(["continue", "go on", "keep going", "resume", "continue please", "please continue", "carry on"]).has(normalized);
}

function precedingObjective(messages, assistantIndex) {
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (message?.role === "user" && cleanText(message.content)) return clipped(message.content, 1200);
  }
  return "";
}

export function masterFrontierContinuationContext(session = {}, options = {}) {
  const messages = Array.isArray(session.messages) ? session.messages : [];
  const timelineRows = typeof options.timelineRows === "function" ? options.timelineRows : () => [];
  const index = messages.findLastIndex((message) => message?.role === "assistant");
  if (index < 0) return null;
  const message = messages[index];
  const objective = cleanText(message.original_objective || precedingObjective(messages, index));
  const previousRunId = cleanText(message.run_id);
  if (!objective || !previousRunId) return null;
  const resumeCheckpoint = boundedResumeCheckpoint(message);
  return {
    schema: "hermes.wasm_agent.avatar_chat.continuation_context.v2",
    source: "avatar-chat-session",
    requested: true,
    original_objective: objective,
    previous_run_id: previousRunId,
    previous_turn_id: cleanText(message.turn_id),
    previous_status: cleanText(message.agent_run_status || (message.pending ? "running" : "")),
    previous_phase: cleanText(message.phase),
    previous_answer: clipped(message.content, 900),
    changed_files: (Array.isArray(message.changed_files) ? message.changed_files : [])
      .map((file) => cleanText(file?.path || file?.file || file))
      .filter(Boolean)
      .slice(0, 12),
    timeline: timelineRows(message, 12),
    resume_key: cleanText(message.resume_key || `${message.run_id || "run"}:${message.turn_id || message.id || "turn"}`),
    ...(resumeCheckpoint ? { resume_checkpoint: resumeCheckpoint } : {}),
    instruction: "Resume the original objective from durable receipts. Inspect existing proof before repeating any side effect.",
  };
}

export function requiredMasterFrontierContinuationContext(text = "", session = {}, options = {}) {
  if (!isAgentContinuationRequest(text)) return null;
  const context = masterFrontierContinuationContext(session, options);
  if (context) return context;
  const error = new Error("A continuation request requires the immediately preceding server run.");
  error.code = "continuation_source_required";
  throw error;
}

export function markMasterFrontierInterrupted(message = {}, error = {}) {
  const reason = cleanText(error.message || error, "run interrupted");
  const resumeCheckpoint = boundedResumeCheckpoint(error) || boundedResumeCheckpoint(message);
  return {
    ...message,
    pending: false,
    resumable: true,
    agent_run_status: "interrupted",
    phase: "Ready to continue",
    content: clipped(message.content || `Interrupted: ${reason}`, 1200),
    resume_error: reason,
    resume_key: cleanText(message.resume_key || `${message.run_id || "run"}:${message.turn_id || message.id || "turn"}`),
    ...(resumeCheckpoint ? { resume_checkpoint: resumeCheckpoint } : {}),
  };
}

export async function resolvePendingAgentRunId(session = {}, message = {}, options = {}) {
  const existing = cleanText(message.run_id);
  if (existing) return existing;
  const turnId = cleanText(message.turn_id);
  const sessionId = cleanText(session.id);
  if (!turnId || !sessionId || typeof options.fetchRuns !== "function") {
    Object.assign(message, markMasterFrontierInterrupted(message, new Error("Saved assistant run has no recoverable server identity.")));
    return "";
  }
  try {
    const payload = await options.fetchRuns(sessionId, options);
    const runs = Array.isArray(payload?.runs) ? payload.runs : [];
    const match = runs.find((run) => cleanText(run?.turn_id) === turnId);
    if (match?.run_id) return cleanText(match.run_id);
    Object.assign(message, markMasterFrontierInterrupted(message, new Error("Saved assistant run is no longer available.")));
  } catch (error) {
    Object.assign(message, markMasterFrontierInterrupted(message, error));
  }
  return "";
}

export async function recoverMasterFrontierFinal(pendingMessage = {}, options = {}) {
  const runId = cleanText(pendingMessage.run_id);
  if (!runId || typeof options.fetchRun !== "function") return null;
  try {
    const payload = await options.fetchRun(runId, options);
    const run = payload?.run && typeof payload.run === "object" ? payload.run : null;
    if (run?.status === "interrupted" && run.error) {
      Object.assign(pendingMessage, markMasterFrontierInterrupted(pendingMessage, run.error));
    }
    return run?.status === "completed" && run.final ? run.final : null;
  } catch (error) {
    Object.assign(pendingMessage, markMasterFrontierInterrupted(pendingMessage, error));
    return null;
  }
}

export function masterFrontierPartialReplyIsStale(text = "") {
  const value = cleanText(text).toLowerCase();
  if (!value) return false;
  return /\bnot\s+inspected\s+yet\b/.test(value)
    || /\bi\s+(do\s+not|don't)\s+have\s+inspected\s+evidence\s+yet\b/.test(value)
    || /\bneed\s+to\s+(inspect|read|recover|locate|check|look\s+up|look\s+into|search)\b/.test(value)
    || /\b(checking|inspecting|searching|looking\s+into)\b.*\b(repo|codebase|source|files?|definitions?)\b.*\bnow\b/.test(value)
    || /\bdispatch\s+kernel\.(inspect|resolve|prove|act|search)\b/.test(value)
    || /\broute[_\s-]+to[_\s-]+kernel[_\s-]+inspect\b/.test(value);
}

export function masterFrontierPartialReplyFromPending(pendingMessage = {}) {
  if (!pendingMessage.agent_delta_started) return "";
  const text = cleanText(pendingMessage.content);
  return text.length >= 80 && !masterFrontierPartialReplyIsStale(text) ? text : "";
}

export function masterFrontierPartialReplyFromError(error = {}, pendingMessage = {}) {
  return cleanText(error.partial_reply || error.payload?.partial_reply || masterFrontierPartialReplyFromPending(pendingMessage));
}
