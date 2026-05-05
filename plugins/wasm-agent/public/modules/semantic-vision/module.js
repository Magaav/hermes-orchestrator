export const moduleDefinition = {
  id: "semantic-vision",
  title: "Semantic Vision",
  status: "lazy planned",
  detail: "Reserved for optional embedding or classifier evidence when a small local vision runtime is available.",
  defaultEnabled: false,
  firmware: "/modules/semantic-vision/module.js",
  analyzer: {
    kind: "image",
    mode: "lazy-singleton",
    cache: "promise + model function",
    evidence: "semantic_labels",
    candidate_library: "onnxruntime-web or WebNN/WebGPU model",
  },
};
