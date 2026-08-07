export const moduleDefinition = {
  id: "artifact-foundry",
  title: "Artifact Foundry",
  status: "candidate deterministic generator",
  detail: "Generates content-addressed structured artifacts from bounded recipes with a WASM transform core and explicit verification receipts.",
  defaultEnabled: true,
  firmware: "/modules/artifact-foundry/runtime.js",
  artifact: "/modules/artifact-foundry/artifact.json",
  recipeSchema: "hermes.wasm_agent.artifact.recipe.v1",
  receiptSchema: "hermes.wasm_agent.artifact.receipt.v1",
  endpoints: [],
  state: {
    input: "ephemeral browser memory",
    output: "operator-exported artifact",
    networkPolicy: "generator-network-denied"
  }
};
