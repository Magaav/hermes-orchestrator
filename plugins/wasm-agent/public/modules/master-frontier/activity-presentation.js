export function showMasterFrontierRunActivity(message = {}, socialChat = false) {
  if (socialChat || message?.role !== "assistant") return false;
  return message?.pending === true
    || Boolean(message?.actions?.length)
    || Boolean(message?.timeline?.length)
    || Boolean(message?.token_ledger)
    || Boolean(message?.changed_files?.length)
    || Boolean(message?.decision_trace?.length);
}

function clean(value) {
  return String(value || "").trim();
}

export function masterFrontierPublicCommentary(action = {}) {
  const commentary = action?.arguments?.commentary;
  if (
    commentary?.schema !== "master.frontier.v6.commentary.v1"
    || commentary?.authored_by !== "model"
    || commentary?.visibility !== "public"
  ) return "";
  return clean(commentary.message).slice(0, 600);
}

export function masterFrontierInitialDecisionTrace() {
  return [{ id: "decision_initial", message: masterFrontierInitialCommentary(), phase: "intake" }];
}

export function appendMasterFrontierDecisionTrace(entries = [], action = {}, message = "") {
  const text = clean(message);
  if (!text) return Array.isArray(entries) ? entries : [];
  const trace = Array.isArray(entries) ? [...entries] : [];
  const commentary = action?.arguments?.commentary || {};
  const id = clean(action?.id) || `decision_${trace.length + 1}`;
  const next = {
    id,
    message: text,
    phase: clean(commentary.phase || action?.arguments?.phase),
    decision: Number.isFinite(Number(action?.arguments?.decision)) ? Number(action.arguments.decision) : null,
  };
  const existing = trace.findIndex((entry) => clean(entry?.id) === id);
  if (existing >= 0) trace[existing] = { ...trace[existing], ...next };
  else trace.push(next);
  return trace.slice(-80);
}

export function masterFrontierDecisionTraceEntries(message = {}) {
  const stored = Array.isArray(message?.decision_trace) ? message.decision_trace : [];
  if (stored.length) return stored;
  const recovered = (Array.isArray(message?.actions) ? message.actions : [])
    .map((action) => {
      const commentary = masterFrontierPublicCommentary(action);
      return commentary ? appendMasterFrontierDecisionTrace([], action, commentary)[0] : null;
    })
    .filter(Boolean);
  if (recovered.length) return recovered.slice(-80);
  if (message?.mode === "direct_head" && message?.pending === true && clean(message?.content)) {
    return [{ id: "decision_legacy_pending", message: clean(message.content), phase: clean(message.phase) }];
  }
  return [];
}

export function showMasterFrontierAnswerBody(message = {}) {
  return message?.mode !== "direct_head"
    || message?.pending !== true
    || message?.agent_delta_started === true;
}

export function masterFrontierHeartbeatBodyContent(message = {}, nextContent = "") {
  if (message?.mode === "direct_head" && message?.pending === true) return clean(message?.content);
  return clean(nextContent) || clean(message?.content);
}

export function renderMasterFrontierDecisionTrace(message = {}, documentRef = globalThis.document) {
  const trace = masterFrontierDecisionTraceEntries(message);
  if (!trace.length || !documentRef?.createElement) return null;
  const wrap = documentRef.createElement("section");
  wrap.className = "agent-timeline agent-decision-trace";
  const rows = documentRef.createElement("div");
  rows.className = "agent-timeline-rows";
  for (const entry of trace) {
    const row = documentRef.createElement("div");
    row.className = "agent-message-body agent-decision-trace-row";
    const label = documentRef.createElement("span");
    label.className = "agent-timeline-detail agent-decision-trace-text";
    label.textContent = clean(entry?.message);
    row.append(label);
    rows.append(row);
  }
  wrap.append(rows);
  return wrap;
}

export function renderMasterFrontierRunDetails(nodes = {}, message = {}, documentRef = globalThis.document) {
  const content = [nodes.changedFiles, nodes.timeline, nodes.tokenLedger, nodes.actions, nodes.decisionTrace].filter(Boolean);
  if (!content.length || !documentRef?.createElement) return null;
  const details = documentRef.createElement("details");
  details.className = "agent-actions-chain agent-run-details";
  const summary = documentRef.createElement("summary");
  summary.className = "agent-actions-summary";
  const label = documentRef.createElement("span");
  label.textContent = message?.pending ? clean(message?.phase) || "Assistant details" : "Assistant details";
  summary.append(label);
  const body = documentRef.createElement("div");
  body.className = "agent-actions-list agent-run-details-body";
  body.append(...content);
  details.append(summary, body);
  return details;
}

export function masterFrontierMessageContentNodes(nodes = {}) {
  return [
    nodes.header,
    nodes.runDetails,
    nodes.body,
    nodes.commandChoices,
  ].filter(Boolean);
}

export function masterFrontierActivityText(item = {}) {
  const eventType = String(item.event_type || item.label || "").trim().toLowerCase();
  const detail = String(item.detail || "").trim();
  if (eventType === "llm.reason.summary" && detail) return detail;
  return "";
}

export function masterFrontierInitialCommentary() {
  return "I’m thinking through your request now.";
}
