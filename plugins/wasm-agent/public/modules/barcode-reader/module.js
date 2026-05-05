export const moduleDefinition = {
  id: "barcode-reader",
  title: "Barcode Reader",
  status: "lazy evidence",
  detail: "Checks attached images for QR/barcodes on demand, then keeps the detector function cached in memory.",
  defaultEnabled: true,
  firmware: "/modules/barcode-reader/module.js",
  analyzer: {
    kind: "image",
    mode: "lazy-singleton",
    cache: "promise + detector function",
    evidence: "barcode",
    native_api: "BarcodeDetector",
  },
};
