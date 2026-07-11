export const MASTER_FRONTIER_V3_SCHEMA = "hermes.wasm_agent.master_frontier.v3";
export const MASTER_FRONTIER_V3_CYPHER = "c3";

export function masterFrontierV3OutputBudget() {
  return 32768;
}

export function masterFrontierV3Instructions() {
  return "C3: reason like Codex; output either the final answer or exactly one semantic operation line with no prose, for example @search query='term'. Use returned file paths with @read. The host scopes and executes; never claim unobserved proof.";
}
