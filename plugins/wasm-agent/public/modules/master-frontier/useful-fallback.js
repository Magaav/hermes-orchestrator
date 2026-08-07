const DEFAULT_ROUTE_ID = "wasm-agent.avatar-chat.ui";
const DEFAULT_SURFACE = "avatar-chat";

function cleanText(value, fallback = "") {
  return String(value ?? fallback).replace(/\s+/g, " ").trim() || fallback;
}

function normalizedPrompt(value) {
  return cleanText(value).toLowerCase();
}

function providerFailureKind(context = {}) {
  const diagnostic = context.diagnostic && typeof context.diagnostic === "object" ? context.diagnostic : {};
  const evidence = cleanText([
    diagnostic.code,
    diagnostic.category,
    diagnostic.mode,
    diagnostic.message,
    context.reason,
  ].filter(Boolean).join(" ")).toLowerCase();
  if (/\b(?:insufficient (?:balance|credits?|funds)|billing(?:[_ -](?:required|incomplete))?|payment required)\b/.test(evidence)) {
    return "billing_required";
  }
  return "unknown";
}

function userObjectiveSummary(userMessage = "") {
  const objective = cleanText(userMessage);
  return objective.length > 240 ? `${objective.slice(0, 237).trim()}...` : objective;
}

export function masterFrontierObjectiveKind(userMessage = "") {
  const prompt = normalizedPrompt(userMessage);
  const mutationCommand = /\b(?:add|apply|build|change|create|edit|implement|patch|refactor|remove|repair|ship|update|wire)\b/.test(prompt);
  const explicitMutationDirective = /\b(?:i\s+(?:need|want)\s+you\s+to|please|can\s+you|could\s+you|go\s+ahead\s+and|let(?:'|’)s)\b[^.!?\n]{0,120}\b(?:add|apply|build|change|create|edit|implement|patch|refactor|remove|repair|ship|update|wire)\b/.test(prompt);
  const explicitVerification = /^(?:please\s+)?(?:verify|validat(?:e|es|ed|ing)|test|check|prove)\b/.test(prompt)
    && /\b(?:current|existing|revision|result|receipt|evidence|change(?:d|s)?|file|code|repo|implementation|component|module|route|ui|test|proof)\w*\b/.test(prompt)
    && !mutationCommand;
  const verificationWorkflow = /\b(?:current|existing|preserve|revision-bound)\b/.test(prompt)
    && [
      /\b(?:run|execute)\b[^.]{0,80}\btest\b/,
      /\binspect\b[^.]{0,80}\bdiff\b/,
      /\b(?:collect|report|finalize)\b[^.]{0,100}\b(?:proof|evidence|receipt)\b/,
    ].filter((pattern) => pattern.test(prompt)).length >= 2
    && !mutationCommand;
  const verification = explicitVerification || verificationWorkflow;
  if (verification) return "verification";
  const implementation = explicitMutationDirective || /\b(?:build(?:s|ing)?|built|implement(?:s|ed|ing)?|edit(?:s|ed|ing)?|patch(?:es|ed|ing)?|chang(?:e|es|ed|ing)|fix(?:es|ed|ing)?|repair(?:s|ed|ing)?|creat(?:e|es|ed|ing)|add(?:s|ed|ing)?|remov(?:e|es|ed|ing)|wir(?:e|es|ed|ing)|ship(?:s|ped|ping)?)\b/.test(prompt)
    && /\b(file|code|repo|implementation|component|module|route|ui|test|proof|bug|issue|feature)\w*\b/.test(prompt);
  if (implementation) return "implementation";
  if (/\b(debug|diagnos\w*|why|fail\w*|inspect\w*|investigat\w*|audit\w*|review\w*|crit\w*|root[- ]cause)\b/.test(prompt)) {
    return "diagnosis";
  }
  return "model_decision";
}

export function masterFrontierOutputBudget(userMessage = "") {
  return masterFrontierObjectiveKind(userMessage) === "diagnosis" ? 1800 : 900;
}

export function masterFrontierRouteId(objectiveKind = "") {
  return cleanText(objectiveKind).toLowerCase() === "implementation"
    ? "wasm-agent.space.ui"
    : DEFAULT_ROUTE_ID;
}

export function masterFrontierUsefulFallback(userMessage = "", context = {}) {
  const diagnostic = context.diagnostic && typeof context.diagnostic === "object" ? context.diagnostic : {};
  const reason = cleanText(context.reason || diagnostic.message || "direct-head response interrupted");
  const routeId = cleanText(context.route_id || context.routeId, DEFAULT_ROUTE_ID);
  const surface = cleanText(context.surface, DEFAULT_SURFACE);
  const objective = userObjectiveSummary(context.original_objective || userMessage);
  const failureKind = providerFailureKind(context);
  if (failureKind === "billing_required") {
    return {
      schema: "hermes.wasm_agent.master_frontier.useful_fallback.v2",
      status: "provider_billing_required",
      answer: [
        "The configured model provider could not answer because its account balance or billing is not active.",
        `Reason: ${reason}`,
        "Add funds or switch to a funded provider before retrying.",
      ].join("\n"),
      route_id: routeId,
      surface,
      reason,
      objective,
      objective_kind: masterFrontierObjectiveKind(objective),
      continuation_context: null,
      metrics: {
        objectivePreserved: Boolean(objective),
        sideEffectReplayGuarded: false,
        proofHonest: true,
        resumable: false,
        failureKind,
      },
    };
  }
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
