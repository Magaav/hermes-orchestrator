import { moduleDefinition as hmr } from "./hmr/module.js";
import { moduleDefinition as observation } from "./observation/module.js";
import { moduleDefinition as browser } from "./browser/module.js";
import { moduleDefinition as assistant } from "./assistant/module.js";
import { moduleDefinition as timeline } from "./timeline/module.js";
import { moduleDefinition as imageCardCore } from "./image-card-core/module.js";
import { moduleDefinition as barcodeReader } from "./barcode-reader/module.js";
import { moduleDefinition as ocr } from "./ocr/module.js";
import { moduleDefinition as cvShapes } from "./cv-shapes/module.js";
import { moduleDefinition as semanticVision } from "./semantic-vision/module.js";

export const MODULE_DEFINITIONS = [
  hmr,
  observation,
  browser,
  assistant,
  timeline,
  imageCardCore,
  barcodeReader,
  ocr,
  cvShapes,
  semanticVision,
];
