const DEFAULT_MAX_CHARS = 3_800_000;

function bounded(value, depth = 0, key = "") {
  if (value == null || typeof value === "boolean" || typeof value === "number") return value;
  if (typeof value === "string") {
    const limit = key === "data_url" ? 1_500_000 : key === "content" ? 40_000 : 6_000;
    return value.length <= limit ? value : `${value.slice(0, limit - 3)}...`;
  }
  if (depth >= 6) return "[bounded]";
  if (Array.isArray(value)) return value.slice(-60).map((item) => bounded(item, depth + 1, key));
  if (typeof value !== "object") return String(value).slice(0, 1000);
  return Object.fromEntries(
    Object.entries(value).slice(0, 120).map(([childKey, child]) => [
      childKey,
      bounded(child, depth + 1, childKey),
    ])
  );
}

function compactMessage(message = {}) {
  const result = { ...message };
  for (const key of ["actions", "timeline", "diagnostics", "token_ledger", "route_contract", "context_preview"]) {
    if (result[key] != null) result[key] = bounded(result[key], 0, key);
  }
  return bounded(result, 0);
}

function compactSession(session = {}) {
  return {
    ...session,
    messages: (Array.isArray(session.messages) ? session.messages : []).slice(-60).map(compactMessage),
    diagnostics: bounded(session.diagnostics, 0, "diagnostics"),
    context_preview: bounded(session.context_preview, 0, "context_preview"),
  };
}

function minimalMessage(message = {}) {
  const diagnostics = message.diagnostics && typeof message.diagnostics === "object" ? message.diagnostics : {};
  return {
    id: message.id,
    role: message.role,
    content: String(message.content || "").slice(0, 20_000),
    timestamp: message.timestamp,
    pending: Boolean(message.pending),
    phase: message.phase,
    run_id: message.run_id,
    turn_id: message.turn_id,
    agent_run_status: message.agent_run_status,
    diagnostics: {
      diff_seen: diagnostics.diff_seen === true,
      proof_seen: diagnostics.proof_seen === true,
      checks_passed: diagnostics.checks_passed === true,
      observed_changed_files: bounded(diagnostics.observed_changed_files, 0, "observed_changed_files"),
      changed_files_complete: diagnostics.changed_files_complete === true,
    },
    changed_files: bounded(message.changed_files, 0, "changed_files"),
  };
}

export function serializeAgentSessions(sessions = [], activeSessionId = "", maxChars = DEFAULT_MAX_CHARS) {
  const result = (Array.isArray(sessions) ? sessions : []).slice(0, 20).map(compactSession);
  let serialized = JSON.stringify(result);
  if (serialized.length <= maxChars) return serialized;

  for (const session of result) {
    if (session.id === activeSessionId || !Array.isArray(session.messages)) continue;
    session.messages = session.messages.slice(-4);
  }
  serialized = JSON.stringify(result);
  if (serialized.length <= maxChars) return serialized;

  for (let index = result.length - 1; index >= 0 && serialized.length > maxChars; index -= 1) {
    if (result[index]?.id === activeSessionId) continue;
    result.splice(index, 1);
    serialized = JSON.stringify(result);
  }
  if (serialized.length <= maxChars) return serialized;

  const active = result.find((session) => session.id === activeSessionId) || result[0] || {};
  const minimal = {
    id: active.id,
    kind: active.kind,
    title: active.title,
    created_at: active.created_at,
    updated_at: active.updated_at,
    messages: (Array.isArray(active.messages) ? active.messages : []).slice(-12).map(minimalMessage),
  };
  return JSON.stringify([minimal]);
}
