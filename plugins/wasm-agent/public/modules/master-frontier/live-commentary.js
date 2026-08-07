function clean(value) {
  return String(value || "").trim();
}

export function masterFrontierLiveStepFromPayload(payload = {}) {
  if (!payload || typeof payload !== "object") return "";
  if (payload.action && typeof payload.action === "object") return masterFrontierLiveStepFromAction(payload.action);
  const phase = clean(payload.phase);
  if (!phase || phase === "Hermes bridge active") return "";
  return phase;
}

export function masterFrontierLiveStepFromAction(action = {}) {
  if (!action || typeof action !== "object") return "";
  const label = clean(action.label);
  const status = clean(action.status).toLowerCase();
  const meta = clean(action.meta);
  const detail = clean(action.detail);
  if (!label || label === "tokens.used" || label === "bridge.run.poll") return "";
  if (["patch", "repo.edit", "apply_patch"].includes(label)) return "Hermes: editing files";
  if (["test.run", "run_tests"].includes(label)) return "Hermes: running tests";
  if (["bridge.run.completed", "backend.run.completed"].includes(label)) return "Hermes: preparing final";
  if (label === "bridge.run.started") return "Dispatching Hermes";
  if (label === "backend.tool.started") return "Starting tool";
  if (label === "backend.tool.completed") return "Reviewing tool result";
  if (meta.startsWith("tool.started") || status === "running") {
    if (label === "execute_code") {
      const match = detail.match(/['"]([^'"]+\.(?:test|spec)\.[A-Za-z0-9]+|[^'"]+\.test\.[A-Za-z0-9]+)['"]/);
      return match ? "Hermes: running tests" : "Running code";
    }
    if (label === "read_file") return "Reading file";
    return `Running ${label}`;
  }
  if ((meta.startsWith("tool.completed") || meta.startsWith("tool.finished")) && status === "done") return `Finished ${label}`;
  if (status === "error") return `${label} needs attention`;
  return "";
}

export function masterFrontierCommentaryFromAction(action = {}) {
  const eventType = clean(action.event_type || action.meta || action.label).toLowerCase();
  const detail = clean(action.detail);
  const publicUpdate = action.arguments?.commentary;
  const protocol = clean(action.arguments?.protocol || action.protocol).toLowerCase();
  if (
    eventType === "llm.reason.summary"
    && publicUpdate?.schema === "master.frontier.v6.commentary.v1"
    && publicUpdate?.authored_by === "model"
    && publicUpdate?.visibility === "public"
  ) {
    return clean(publicUpdate.message).slice(0, 600);
  }
  if (protocol === "v6") {
    if (["llm.inference.started", "command.started", "evidence.received"].includes(eventType)) return "";
    if (eventType === "llm.reason.summary") return "";
    if (eventType === "semantic.decision") {
      const tool = clean(action.arguments?.tool).toLowerCase();
      const matches = Number(action.arguments?.matches || 0);
      const details = Array.isArray(action.arguments?.details) ? action.arguments.details : [];
      if (tool === "discover" && matches > 0) {
        return `I found ${matches} route-authorized ${matches === 1 ? "capability" : "capabilities"} and I’m narrowing the executable path.`;
      }
      if (tool === "detail" && details.length > 0) {
        const capabilities = details.filter((item) => item?.kind === "capability" && item?.found).length;
        const evidence = details.filter((item) => item?.kind === "evidence" && item?.found).length;
        if (capabilities && evidence) return `I loaded ${capabilities} capability ${capabilities === 1 ? "schema" : "schemas"} and ${evidence} evidence ${evidence === 1 ? "lens" : "lenses"}.`;
        if (capabilities) return `I loaded ${capabilities} capability ${capabilities === 1 ? "schema" : "schemas"} for the next operation.`;
        if (evidence) return `I loaded ${evidence} bounded evidence ${evidence === 1 ? "lens" : "lenses"} for the next decision.`;
      }
      return "";
    }
  }
  const fixed = {
    "route.resolved": "I found the owning route. I’m inspecting the relevant implementation now.",
    "envelope.created": "I’ve bounded the request and started the run.",
    "head.started": "I’m working through the request now.",
    "llm.inference.started": detail && /decision\s+\d+/i.test(detail)
      ? `Choosing the next bounded action (${detail.toLowerCase()}).`
      : "Choosing the next bounded action.",
    "llm.reason.summary": "I’ve reviewed the current evidence and I’m choosing the next step.",
    "semantic.decision": "I’ve selected the next bounded operation.",
    "command.proposed": "I’ve prepared the next operation.",
    "command.accepted": "The next operation passed the run policy.",
    "command.dispatched": "I’m running the selected operation now.",
    "command.started": "I’m running the selected operation now.",
    "evidence.received": detail ? `Checking new evidence: ${detail}` : "Checking newly received evidence.",
    "evidence.missing": "That check did not provide enough evidence, so I’m narrowing the next step.",
    "command.failed": "That operation failed; I’m using the failure evidence to adjust.",
    "gate.started": "I’m verifying the result before answering.",
    "gate.decision": "The verification gate has finished. I’m preparing the answer.",
    "answer.started": "I have enough evidence. I’m preparing the final answer.",
    "duplicate_action_repair_requested": "That action repeated existing evidence. I’m switching to a permitted alternative.",
    "workflow_stage_action_rejected": "That tool belongs to a completed stage. I’m advancing to the active stage.",
    "novelty_action_rejected": "That action would not add evidence. I’m choosing a different operation.",
    "action_completed_without_novelty": "The operation completed without new evidence. I’m changing approach.",
    "no_semantic_progress": "I could not make bounded progress, so I’m stopping instead of looping.",
  };
  if (fixed[eventType]) return fixed[eventType];
  if (eventType === "head.decision" && detail) return detail;
  return masterFrontierLiveStepFromAction(action);
}
