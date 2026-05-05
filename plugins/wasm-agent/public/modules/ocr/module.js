export const moduleDefinition = {
  id: "ocr",
  title: "OCR",
  status: "lazy OCR",
  detail: "Tries native TextDetector first, then lazy-loads and caches a Tesseract.js OCR runtime when needed.",
  defaultEnabled: true,
  firmware: "/modules/ocr/module.js",
  analyzer: {
    kind: "image",
    mode: "lazy-singleton",
    cache: "promise + detector/worker function",
    evidence: "text",
    native_api: "TextDetector",
    fallback_library: "tesseract.js",
    default_runtime_url: "https://cdn.jsdelivr.net/npm/tesseract.js@5/dist/tesseract.min.js",
  },
};
