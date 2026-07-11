const SOURCE_OBJECT_RE = /\b(code|source|repo|repository|file|module|component|widget|class|function|symbol|definition|implementation|route|endpoint|event|schema)\w*\b/i;
const INVESTIGATION_RE = /\b(crit\w*|review\w*|audit\w*|investigat\w*|inspect\w*|analy[sz]\w*|diagnos\w*|root[- ]cause)\b/i;

export const MASTER_FRONTIER_V4_PROTOCOL = "v4-source-investigation";
export const MASTER_FRONTIER_V4_MODE = "source-investigation-read-only";
export const MASTER_FRONTIER_V4_SCHEMA = "hermes.wasm_agent.master_frontier.v4.request.v1";
export const MASTER_FRONTIER_V5_PROTOCOL = "v5";
export const MASTER_FRONTIER_V5_SCHEMA = "hermes.wasm_agent.master_frontier.v5";

export function masterFrontierProtocolRequest(objective = "", objectiveKind = "", explicitProtocol = "") {
  const requested = String(explicitProtocol || "").trim();
  if (requested === "v3") return { protocol: "v3", investigation_mode: "", schema: "hermes.wasm_agent.master_frontier.v3" };
  if (requested === MASTER_FRONTIER_V4_PROTOCOL) return { protocol: MASTER_FRONTIER_V4_PROTOCOL, investigation_mode: MASTER_FRONTIER_V4_MODE, schema: MASTER_FRONTIER_V4_SCHEMA };
  return { protocol: MASTER_FRONTIER_V5_PROTOCOL, investigation_mode: "", schema: MASTER_FRONTIER_V5_SCHEMA };
}

export function masterFrontierExplicitProtocol(search = "", stored = "") {
  const requested = new URLSearchParams(String(search || "")).get("frontier") || String(stored || "");
  return ["v3", MASTER_FRONTIER_V4_PROTOCOL, MASTER_FRONTIER_V5_PROTOCOL].includes(requested) ? requested : MASTER_FRONTIER_V5_PROTOCOL;
}

export function masterFrontierSourceInvestigationRequest(objective = "", objectiveKind = "") {
  const text = String(objective || "").trim();
  const sourceInvestigation = objectiveKind === "diagnosis" && SOURCE_OBJECT_RE.test(text) && INVESTIGATION_RE.test(text);
  return sourceInvestigation
    ? { protocol: MASTER_FRONTIER_V4_PROTOCOL, investigation_mode: MASTER_FRONTIER_V4_MODE, schema: MASTER_FRONTIER_V4_SCHEMA }
    : { protocol: "v3", investigation_mode: "", schema: "hermes.wasm_agent.master_frontier.v3" };
}
