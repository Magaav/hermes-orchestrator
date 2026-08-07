const number = (value) => Number.isFinite(Number(value)) ? Math.max(0, Math.floor(Number(value))) : null;

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

export function masterFrontierStatusModel({ sessionId = "", diagnostics = {} } = {}) {
  const contextUsed = latestContextTokens(diagnostics);
  const contextWindow = firstNumber(diagnostics, ["context_window_tokens", "model_context_window", "context_window"])
    ?? firstNumber(diagnostics.token_usage_total || {}, ["context_window_tokens", "model_context_window", "context_window"])
    ?? firstNumber(diagnostics.runtime || {}, ["context_window_tokens", "model_context_window", "context_window"]);
  const limits = diagnostics.rate_limits || diagnostics.rateLimits || diagnostics.token_usage_total?.rate_limits || {};
  const weekly = limits.seven_day || limits.sevenDay || limits.weekly || {};
  const weeklyLeft = firstNumber(weekly, ["percent_left", "percentLeft", "remaining_percent"]);
  const weeklyUsed = firstNumber(weekly, ["percent_used", "percentUsed"]);
  return {
    sessionId: String(sessionId || diagnostics.session_id || "-") ,
    contextUsed,
    contextWindow,
    contextLeft: contextUsed !== null && contextWindow !== null ? percentageLeft(contextUsed, contextWindow) : null,
    weeklyLeft: weeklyLeft ?? (weeklyUsed !== null ? Math.max(0, 100 - weeklyUsed) : null),
    weeklyReset: String(weekly.resets_at_label || weekly.resetsAtLabel || weekly.resets_at || weekly.resetsAt || ""),
  };
}

export function mergeMasterFrontierStatusUsage(usage = {}, previous = {}) {
  const merged = { ...(usage || {}) };
  for (const key of ["active_context_tokens", "context_window_tokens", "rate_limits"]) {
    if (previous?.[key] !== undefined) merged[key] = previous[key];
  }
  return merged;
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
  const model = masterFrontierStatusModel(input);
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
  const contextText = model.contextWindow === null || model.contextUsed === null
    ? `${compact(model.contextUsed)} used / window unavailable`
    : `${model.contextLeft}% left (${model.contextUsed.toLocaleString()} used / ${compact(model.contextWindow)})`;
  body.append(row("Context:", contextText));

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
    ? "unavailable"
    : `${model.weeklyLeft}% left${resetLabel ? ` (resets ${resetLabel})` : ""}`;
  allowance.append(element(document, "span", "codex-status__weekly-text", weeklyText));
  body.append(row("7d limit:", "", allowance));

  root.replaceChildren(header, body);
  root.dataset.statusReady = "true";
  return model;
}
