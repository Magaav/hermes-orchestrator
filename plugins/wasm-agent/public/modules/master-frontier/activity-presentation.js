export function showMasterFrontierRunActivity(message = {}, socialChat = false) {
  return !socialChat && message?.role === "assistant" && message?.pending === true;
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
