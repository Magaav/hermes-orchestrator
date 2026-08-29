const number = (value) => Number.isFinite(Number(value)) ? Math.max(0, Math.floor(Number(value))) : null;
const REASONING_STORAGE_KEY = "wasmAgent.masterFrontierReasoningEffort";
const REASONING_EFFORTS = Object.freeze([
  ["none", "None"], ["low", "Light"], ["medium", "Medium"],
  ["high", "High"], ["xhigh", "XHigh"], ["max", "Max"],
]);
const REASONING_VALUES = new Set(REASONING_EFFORTS.map(([value]) => value));

export function normalizeMasterFrontierReasoningEffort(value) {
  const normalized = String(value || "").trim().toLowerCase();
  return REASONING_VALUES.has(normalized) ? normalized : "low";
}

export function masterFrontierReasoningEffort(storage = globalThis.localStorage) {
  try {
    return normalizeMasterFrontierReasoningEffort(storage?.getItem(REASONING_STORAGE_KEY));
  } catch {
    return "low";
  }
}

export function setMasterFrontierReasoningEffort(value, storage = globalThis.localStorage) {
  const normalized = normalizeMasterFrontierReasoningEffort(value);
  try { storage?.setItem(REASONING_STORAGE_KEY, normalized); } catch { /* storage is optional */ }
  return normalized;
}

export function masterFrontierRequestPreferences(storage = globalThis.localStorage) {
  return { reasoning_effort: masterFrontierReasoningEffort(storage), text_verbosity: "low" };
}

const firstNumber = (source, keys) => {
  for (const key of keys) {
    const value = number(source?.[key]);
    if (value !== null) return value;
  }
  return null;
};

const compact = (value) => {
  const count = number(value);
  if (count === null) return "-";
  if (count < 1_000) return String(count);
  if (count < 1_000_000) return `${Math.round(count / 100) / 10}K`;
  return `${Math.round(count / 100_000) / 10}M`;
};

const latestContextTokens = (diagnostics = {}) => {
  const active = firstNumber(diagnostics.token_usage_total || {}, ["active_context_tokens"])
    ?? firstNumber(diagnostics, ["active_context_tokens"]);
  if (active !== null) return active;
  const contexts = Array.isArray(diagnostics.context) ? diagnostics.context : [];
  const latest = contexts.at(-1) || {};
  const candidates = [
    latest.provider_usage,
    latest.usage,
    diagnostics.token_usage_head,
    diagnostics.token_usage,
    diagnostics.token_usage_total,
    diagnostics.total_token_usage,
  ];
  for (const usage of candidates) {
    const value = firstNumber(usage || {}, ["prompt_tokens", "input_tokens", "inputTokens"]);
    if (value !== null && value > 0) return value;
  }
  return null;
};

const percentageLeft = (used, total) => total > 0 ? Math.max(0, Math.min(100, Math.round((1 - used / total) * 100))) : null;

export function masterFrontierStatusModel({ sessionId = "", diagnostics = {}, sessionSummary = {}, reasoningEffort = "low" } = {}) {
  const calls = Array.isArray(diagnostics.token_usage) ? diagnostics.token_usage : [];
  const latestCall = calls.at(-1) || {};
  const telemetry = diagnostics.status_telemetry
    || diagnostics.token_usage_total?.status_telemetry
    || latestCall.status_telemetry
    || {};
  const modelName = String(
    telemetry.model?.value
      || diagnostics.direct_head?.model
      || diagnostics.model
      || diagnostics.token_usage_total?.model
      || latestCall.model
      || diagnostics.runtime?.model
      || "",
  ).trim();
  const contextUsed = latestContextTokens(diagnostics);
  const contextWindow = firstNumber(diagnostics, ["context_window_tokens", "model_context_window", "context_window"])
    ?? firstNumber(telemetry.context_window || {}, ["tokens"])
    ?? firstNumber(diagnostics.token_usage_total || {}, ["context_window_tokens", "model_context_window", "context_window"])
    ?? firstNumber(diagnostics.runtime || {}, ["context_window_tokens", "model_context_window", "context_window"]);
  const limits = diagnostics.rate_limits || diagnostics.rateLimits || diagnostics.token_usage_total?.rate_limits || {};
  const weekly = limits.seven_day || limits.sevenDay || limits.weekly || {};
  const weeklyLeft = firstNumber(weekly, ["percent_left", "percentLeft", "remaining_percent"]);
  const weeklyUsed = firstNumber(weekly, ["percent_used", "percentUsed"]);
  const weeklyStatus = String(telemetry.seven_day?.status || (weeklyLeft !== null || weeklyUsed !== null ? "reported" : "unknown"));
  const sessionUsage = sessionSummary?.usage && typeof sessionSummary.usage === "object" ? sessionSummary.usage : {};
  const sessionInput = firstNumber(sessionUsage, ["input_tokens", "prompt_tokens"]);
  const sessionCached = firstNumber(sessionUsage, ["cached_input_tokens", "cache_read_tokens"]) ?? 0;
  return {
    sessionId: String(sessionId || diagnostics.session_id || "-") ,
    modelName: modelName || "not reported",
    reasoningEffort: normalizeMasterFrontierReasoningEffort(reasoningEffort),
    effectiveReasoningEffort: normalizeMasterFrontierReasoningEffort(
      diagnostics.reasoning_effort || diagnostics.reasoningEffort || reasoningEffort,
    ),
    contextUsed,
    contextWindow,
    contextLeft: contextUsed !== null && contextWindow !== null ? percentageLeft(contextUsed, contextWindow) : null,
    sessionTokens: firstNumber(sessionUsage, ["total_tokens"]),
    sessionInput,
    sessionCached,
    sessionFresh: sessionInput === null ? null : Math.max(0, sessionInput - sessionCached),
    sessionTurns: number(sessionSummary?.turns),
    weeklyLeft: weeklyLeft ?? (weeklyUsed !== null ? Math.max(0, 100 - weeklyUsed) : null),
    weeklyStatus,
    weeklyReset: String(weekly.resets_at_label || weekly.resetsAtLabel || weekly.resets_at || weekly.resetsAt || ""),
  };
}

export function mergeMasterFrontierStatusUsage(usage = {}, previous = {}) {
  const merged = { ...(usage || {}) };
  for (const key of ["model", "active_context_tokens", "context_window_tokens", "rate_limits", "status_telemetry"]) {
    if (previous?.[key] !== undefined) merged[key] = previous[key];
  }
  return merged;
}

export function mergeMasterFrontierSessionStatusDiagnostics(diagnostics = {}, messages = []) {
  const current = diagnostics && typeof diagnostics === "object" ? diagnostics : {};
  const prior = [...(Array.isArray(messages) ? messages : [])].reverse().find((message) => {
    const candidate = message?.diagnostics;
    if (!candidate || candidate === current) return false;
    return Boolean(
      candidate.context_window_tokens
      || candidate.status_telemetry?.context_window
      || candidate.token_usage_total?.context_window_tokens
      || candidate.rate_limits?.seven_day
      || candidate.token_usage_total?.rate_limits?.seven_day
    );
  })?.diagnostics || {};
  const priorTotal = prior.token_usage_total && typeof prior.token_usage_total === "object" ? prior.token_usage_total : {};
  const currentTotal = current.token_usage_total && typeof current.token_usage_total === "object" ? current.token_usage_total : {};
  const carry = {};
  for (const key of ["context_window_tokens", "rate_limits", "status_telemetry"]) {
    const value = current[key] ?? currentTotal[key] ?? prior[key] ?? priorTotal[key];
    if (value !== undefined) carry[key] = value;
  }
  return {
    ...current,
    ...carry,
    token_usage_total: { ...priorTotal, ...currentTotal, ...carry },
  };
}

export async function refreshMasterFrontierStatus({ messages = [], refreshLedger } = {}) {
  if (typeof refreshLedger !== "function") return null;
  const message = [...messages].reverse().find((item) => item?.run_id);
  if (!message) return null;
  return { message, result: await refreshLedger(message) };
}

const element = (document, name, className, text = "") => {
  const node = document.createElement(name);
  if (className) node.className = className;
  if (text) node.textContent = text;
  return node;
};

export function renderMasterFrontierStatusPanel(root, input = {}) {
  if (!root) return null;
  const document = root.ownerDocument;
  const selectedReasoning = masterFrontierReasoningEffort(input.storage);
  const model = masterFrontierStatusModel({ ...input, reasoningEffort: selectedReasoning });
  const header = element(document, "header", "codex-status__header");
  header.append(element(document, "strong", "", "Status"));
  const close = element(document, "button", "codex-status__close", "Close");
  close.type = "button";
  close.addEventListener("click", () => {
    const balloon = root.closest("#agentContextBalloon");
    if (balloon) balloon.hidden = true;
    document.querySelector("#agentTokenUsage")?.setAttribute("aria-expanded", "false");
  });
  header.append(close);

  const body = element(document, "div", "codex-status__body");
  const row = (label, value, extra = null) => {
    const line = element(document, "div", "codex-status__row");
    line.append(element(document, "span", "codex-status__label", label));
    const content = element(document, "div", "codex-status__value", value);
    if (extra) content.append(extra);
    line.append(content);
    return line;
  };
  body.append(row("Session:", model.sessionId));
  body.append(row("Model:", model.modelName));
  const reasoningSelect = element(document, "s-select", "codex-status__reasoning");
  reasoningSelect.setAttribute("aria-label", "Thinking weight");
  reasoningSelect.dataset.effectiveReasoningEffort = model.effectiveReasoningEffort;
  for (const [value, label] of REASONING_EFFORTS) {
    const option = element(document, "option", "", label);
    option.value = value;
    option.selected = value === model.reasoningEffort;
    reasoningSelect.append(option);
  }
  reasoningSelect.value = model.reasoningEffort;
  reasoningSelect.addEventListener("change", () => {
    setMasterFrontierReasoningEffort(reasoningSelect.value, input.storage);
  });
  body.append(row("Thinking:", "", reasoningSelect));
  const contextText = model.contextWindow === null || model.contextUsed === null
    ? `${compact(model.contextUsed)} used / window not reported`
    : `${model.contextLeft}% left (${model.contextUsed.toLocaleString()} used / ${compact(model.contextWindow)})`;
  body.append(row("Thread context:", contextText));
  const sessionText = model.sessionTokens === null
    ? "not reported"
    : `${model.sessionTokens.toLocaleString()} total · ${compact(model.sessionFresh)} fresh · ${compact(model.sessionCached)} cached${model.sessionTurns === null ? "" : ` · ${model.sessionTurns} turns`}`;
  body.append(row("Session tokens:", sessionText));

  const allowance = element(document, "div", "codex-status__allowance");
  const meter = element(document, "span", "codex-status__meter");
  const fill = element(document, "span", "codex-status__meter-fill");
  fill.style.width = `${model.weeklyLeft ?? 0}%`;
  meter.append(fill);
  allowance.append(meter);
  let resetLabel = model.weeklyReset;
  if (/^\d{9,}$/.test(resetLabel)) {
    resetLabel = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(new Date(Number(resetLabel) * 1000));
  }
  const weeklyText = model.weeklyLeft === null
    ? (model.weeklyStatus === "provider_omitted" ? "provider omitted" : `telemetry ${model.weeklyStatus}`)
    : `${model.weeklyLeft}% left${resetLabel ? ` (resets ${resetLabel})` : ""}`;
  allowance.append(element(document, "span", "codex-status__weekly-text", weeklyText));
  body.append(row("7d limit:", "", allowance));

  root.replaceChildren(header, body);
  root.dataset.statusReady = "true";
  return model;
}
