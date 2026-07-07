export const MASTER_FRONTIER_CAPS = Object.freeze([
  "repo.read",
  "repo.edit",
  "test.run",
  "command.run",
  "runtime.inspect",
  "docs.update",
  "proof.report",
]);

export const MASTER_FRONTIER_OUTPUT_SCHEMA = Object.freeze({
  type: "object",
  required: ["answer", "decision", "actions", "state_delta", "needs", "confidence"],
  properties: {
    answer: { type: "string" },
    decision: { type: "string" },
    actions: { type: "array", items: { type: "object" } },
    state_delta: { type: "object" },
    needs: { type: "array", items: { type: "string" } },
    proof_requests: { type: "array", items: { type: "string" } },
    confidence: { type: "number" },
  },
  additionalProperties: true,
});

export function masterFrontierAllowedActions(caps = MASTER_FRONTIER_CAPS) {
  return [
    { id: "answer", type: "direct", description: "Answer directly from the envelope when no tool work is required." },
    { id: "transcript.read", type: "kernel", description: "Read bounded exact avatar-chat turns from the current transcript cache when continuity summary is ambiguous." },
    { id: "node.capabilities", type: "kernel", description: "Inspect whether a named Hermes node is alive, model-backed, and answerable through the bridge." },
    { id: "node.chat", type: "kernel", description: "Ask an answerable Hermes node through the bridge prompt/task API when its own brain should answer." },
    { id: "dispatch.hermes", type: "bridge", caps, description: "Dispatch bounded tool/proof work through the wasm-agent Hermes bridge." },
  ];
}
