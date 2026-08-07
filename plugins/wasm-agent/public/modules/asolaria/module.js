export const moduleDefinition = {
  id: "asolaria",
  title: "ASOLARIA Drills",
  status: "experimental; no decision authority",
  detail: "Browser-local receipt and lattice research artifact. Its tested binary predictor adds no value and must not alter agent answers.",
  defaultEnabled: true,
  firmware: "/modules/asolaria/asolaria.entry.js",
  runtime: "/modules/asolaria/runtime.js",
  artifact: "/modules/asolaria/artifact.json",
  artifactSchema: "hermes.wasm_agent.asolaria.artifact.v1",
  receiptSchema: "hermes.wasm_agent.asolaria.receipt.v1",
  calibrationSchema: "hermes.wasm_agent.asolaria.calibration.v1",
  qaEvaluationSchema: "hermes.wasm_agent.asolaria.qa_evaluation.v1",
  latticeSchema: "hermes.wasm_agent.asolaria.lattice.v1",
  latticeRuntime: "/modules/asolaria/structure.js",
  endpoints: [],
  state: {
    runtime: "lazy browser singleton",
    input: "ephemeral browser memory",
    output: "operator-exported receipt only",
    networkPolicy: "no input upload",
    decisionAuthority: "none"
  }
};
