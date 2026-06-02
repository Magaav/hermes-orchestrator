import { moduleDefinition as hmr } from "./hmr/module.js";
import { moduleDefinition as spaces } from "./spaces/module.js";
import { moduleDefinition as observation } from "./observation/module.js";
import { moduleDefinition as devices } from "./devices/module.js";
import { moduleDefinition as nativeStandby } from "./native-standby/module.js";
import { moduleDefinition as artifacts } from "./artifacts/module.js";
import { moduleDefinition as config } from "./config/module.js";
import { moduleDefinition as moduleManager } from "./module-manager/module.js";
import { moduleDefinition as browser } from "./browser/module.js";
import { moduleDefinition as wis } from "./wis/module.js";
import { moduleDefinition as clientState } from "./client-state/module.js";
import { moduleDefinition as assistant } from "./assistant/module.js";
import { moduleDefinition as remoteControl } from "./remote-control/module.js";
import { moduleDefinition as timeline } from "./timeline/module.js";
import { moduleDefinition as imageCardCore } from "./image-card-core/module.js";
import { moduleDefinition as barcodeReader } from "./barcode-reader/module.js";
import { moduleDefinition as ocr } from "./ocr/module.js";
import { moduleDefinition as cvShapes } from "./cv-shapes/module.js";
import { moduleDefinition as semanticVision } from "./semantic-vision/module.js";

export const MODULE_DEFINITIONS = [
  hmr,
  spaces,
  observation,
  devices,
  nativeStandby,
  artifacts,
  config,
  moduleManager,
  browser,
  wis,
  clientState,
  assistant,
  remoteControl,
  timeline,
  imageCardCore,
  barcodeReader,
  ocr,
  cvShapes,
  semanticVision,
];
