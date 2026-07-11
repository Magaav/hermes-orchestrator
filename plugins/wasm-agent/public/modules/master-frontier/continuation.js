function cleanText(value, fallback = "") {
  const text = String(value ?? fallback).replace(/\s+/g, " ").trim();
  return text || fallback;
}

function clipped(value, limit) {
  const text = cleanText(value, "");
  return text.length <= limit ? text : `${text.slice(0, Math.max(0, limit - 3)).trim()}...`;
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
  const candidates = messages
    .map((message, index) => ({ message, index }))
    .filter(({ message }) => message && message.role === "assistant")
    .map(({ message, index }) => {
      const content = cleanText(message.content);
      const status = cleanText(message.agent_run_status).toLowerCase();
      const phase = cleanText(message.phase).toLowerCase();
      const objective = cleanText(message.original_objective || precedingObjective(messages, index));
      const evidenceCount = timelineRows(message, 20).length + (Array.isArray(message.changed_files) ? message.changed_files.length : 0);
      const interrupted = message.pending || status === "interrupted" || message.resumable || phase.includes("resume error");
      return { message, index, objective, score: (interrupted ? 100 : 0) + evidenceCount + (message.run_id ? 5 : 0) };
    })
    .filter((item) => item.objective && item.score > 0)
    .sort((left, right) => right.score - left.score || right.index - left.index);
  const candidate = candidates[0];
  if (!candidate) return null;
  const message = candidate.message;
  return {
    schema: "hermes.wasm_agent.avatar_chat.continuation_context.v2",
    source: "avatar-chat-session",
    original_objective: candidate.objective,
    previous_run_id: cleanText(message.run_id),
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
    instruction: "Resume the original objective from durable receipts. Inspect existing proof before repeating any side effect.",
  };
}

export function markMasterFrontierInterrupted(message = {}, error = {}) {
  const reason = cleanText(error.message || error, "run interrupted");
  return {
    ...message,
    pending: false,
    resumable: true,
    agent_run_status: "interrupted",
    phase: "Ready to continue",
    content: clipped(message.content || `Interrupted: ${reason}`, 1200),
    resume_error: reason,
    resume_key: cleanText(message.resume_key || `${message.run_id || "run"}:${message.turn_id || message.id || "turn"}`),
  };
}

export async function recoverMasterFrontierFinal(pendingMessage = {}, options = {}) {
  const runId = cleanText(pendingMessage.run_id);
  if (!runId || typeof options.fetchRun !== "function") return null;
  try {
    const payload = await options.fetchRun(runId, options);
    const run = payload?.run && typeof payload.run === "object" ? payload.run : null;
    return run?.status === "completed" && run.final ? run.final : null;
  } catch {
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
