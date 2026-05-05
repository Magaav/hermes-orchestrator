export const moduleDefinition = {
  id: "cv-shapes",
  title: "CV Shapes",
  status: "lazy planned",
  detail: "Reserved for on-demand contour, layout, and region evidence beyond the core Canvas metrics.",
  defaultEnabled: false,
  firmware: "/modules/cv-shapes/module.js",
  analyzer: {
    kind: "image",
    mode: "lazy-singleton",
    cache: "promise + cv function",
    evidence: "regions",
    candidate_library: "opencv.js or small WASM CV kernels",
  },
};
