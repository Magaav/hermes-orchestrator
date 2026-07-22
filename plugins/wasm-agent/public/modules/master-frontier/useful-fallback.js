const DEFAULT_ROUTE_ID = "wasm-agent.avatar-chat.ui";
const DEFAULT_SURFACE = "avatar-chat";

function cleanText(value, fallback = "") {
  return String(value ?? fallback).replace(/\s+/g, " ").trim() || fallback;
}

function normalizedPrompt(value) {
  return cleanText(value).toLowerCase();
}

function userObjectiveSummary(userMessage = "") {
  const objective = cleanText(userMessage);
  return objective.length > 240 ? `${objective.slice(0, 237).trim()}...` : objective;
}

export function masterFrontierObjectiveKind(userMessage = "") {
  const prompt = normalizedPrompt(userMessage);
  const implementation = /\b(?:build(?:s|ing)?|built|implement(?:s|ed|ing)?|edit(?:s|ed|ing)?|patch(?:es|ed|ing)?|chang(?:e|es|ed|ing)|fix(?:es|ed|ing)?|repair(?:s|ed|ing)?|creat(?:e|es|ed|ing)|add(?:s|ed|ing)?|remov(?:e|es|ed|ing)|wir(?:e|es|ed|ing)|ship(?:s|ped|ping)?)\b/.test(prompt)
    && /\b(file|code|repo|implementation|component|module|route|ui|test|proof|bug|issue|feature)\w*\b/.test(prompt);
  if (implementation) return "implementation";
  if (/\b(debug|diagnos\w*|why|fail\w*|inspect\w*|investigat\w*|audit\w*|review\w*|crit\w*|root[- ]cause)\b/.test(prompt)) {
    return "diagnosis";
  }
  return "conversation";
}

export function masterFrontierOutputBudget(userMessage = "") {
  return masterFrontierObjectiveKind(userMessage) === "diagnosis" ? 1800 : 900;
}

export function masterFrontierUsefulFallback(userMessage = "", context = {}) {
  const diagnostic = context.diagnostic && typeof context.diagnostic === "object" ? context.diagnostic : {};
  const reason = cleanText(context.reason || diagnostic.message || "direct-head response interrupted");
  const routeId = cleanText(context.route_id || context.routeId, DEFAULT_ROUTE_ID);
  const surface = cleanText(context.surface, DEFAULT_SURFACE);
  const objective = userObjectiveSummary(context.original_objective || userMessage);
  const genuineInterruption = /\b(timeout|transport(?: failure)?|connection reset|network error|interrupted|restart(?:ed)?)\b/i.test(reason);
  if (context.provider_interrupted !== true && !genuineInterruption) return null;
  const kind = masterFrontierObjectiveKind(objective);
  const checkpoint = context.continuation_context && typeof context.continuation_context === "object"
    ? context.continuation_context
    : null;
  const answer = [
    "I was interrupted before I could finish this turn.",
    objective ? `I kept the objective: ${objective}` : "",
    kind === "implementation"
      ? "The next attempt will resume from recorded function results and inspect change/test receipts before repeating a side effect."
      : kind === "diagnosis"
        ? "The next attempt will resume from recorded evidence and finish the diagnosis."
        : "The next attempt will resume from the recorded answer and evidence without asking you to repeat the request.",
    checkpoint?.previous_run_id ? `Saved run: ${checkpoint.previous_run_id}.` : "",
    `Reason: ${reason}`,
  ].filter(Boolean).join("\n");
  return {
    schema: "hermes.wasm_agent.master_frontier.useful_fallback.v2",
    status: "resumable_interruption",
    answer,
    route_id: routeId,
    surface,
    reason,
    objective,
    objective_kind: kind,
    continuation_context: checkpoint,
    metrics: {
      objectivePreserved: Boolean(objective),
      sideEffectReplayGuarded: kind === "implementation",
      proofHonest: true,
    },
  };
}
