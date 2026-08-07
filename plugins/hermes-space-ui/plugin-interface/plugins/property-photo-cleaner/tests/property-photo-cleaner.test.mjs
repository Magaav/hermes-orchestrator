import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { planTiles } from "../modules/tile-planner.js";
import { correctionValues } from "../modules/correction-pipeline.js";
import {
  decodeYoloEOutputs,
  normalizeDetections,
  planDetectionViews,
  suppressOverlaps
} from "../modules/object-detector.js";
import { hasWatermarkChromaEvidence } from "../modules/watermark-recognizer.js";
import { orderDetectionsForCleaning, planDetectionCleanPasses } from "../modules/detection-mask.js";
import { planInpaintingCrop } from "../modules/migan-pipeline.js";
import {
  planQualityMaskRegions,
  planQualitySceneCrop
} from "../modules/quality-scene-crop.js";

const root = fileURLToPath(new URL("..", import.meta.url));
const read = (path) => readFile(join(root, path), "utf8");

test("launcher contains no eager entry, runtime, model, fixture, worker, or WebGPU initialization", async () => {
  const source = await read("property-photo-cleaner.launcher.js");
  assert.match(source, /async function open/);
  assert.match(source, /import\("\.\/property-photo-cleaner\.entry\.js\?v=0\.2\.0"\)/);
  assert.doesNotMatch(source.split("async function open")[0], /property-photo-cleaner\\.entry/);
  assert.doesNotMatch(source, /requestAdapter|new Worker|fixture-manifest|\.tflite|loadVerifiedLiteRt|import\([^)]*litert/i);
});

test("Space initializer adapter imports only the lightweight launcher", async () => {
  const source = await read("ext/js/_core/framework/initializer.js/initialize/end/property-photo-cleaner.js");
  assert.match(source, /property-photo-cleaner\.launcher\.js/);
  assert.doesNotMatch(source, /entry|litert|tflite|worker|fixture/i);
});

test("artifact is compact and excludes private or embedded image data", async () => {
  const artifact = await read("artifact.json");
  assert.ok(Buffer.byteLength(artifact) < 5000);
  assert.doesNotMatch(artifact, /base64|data:image|processedPhoto|photoBlob/i);
  const parsed = JSON.parse(artifact);
  assert.equal(parsed.launchMode, "lazy");
  assert.equal(parsed.models[0].cacheDefault, false);
});

test("admitted browser LaMa model has immutable bytes and static 256px shapes", async () => {
  const model = JSON.parse(await read("models/model-manifest.json"));
  assert.equal(model.status, "browser_wasm_fixture_verified");
  assert.equal(model.runtime.version, "1.27.0");
  assert.match(model.runtime.url, /onnxruntime-web/);
  assert.equal(model.model.status, "verified");
  assert.equal(model.model.accelerator, "wasm");
  assert.deepEqual(model.model.input.image, [1, 3, 256, 256]);
  assert.deepEqual(model.model.input.mask, [1, 1, 256, 256]);
  assert.equal(model.verification.photoNetworkWrites, 0);
  const bytes = await readFile(join(root, "models/lama-256-places2.onnx"));
  assert.equal(createHash("sha256").update(bytes).digest("hex"), model.model.sha256);
});

test("scene-aware quality candidate is commit-pinned and reuses the local WebGPU runtime", async () => {
  const manifest = JSON.parse(await read("models/moebius-manifest.json"));
  assert.equal(manifest.status, "browser_product_verified_candidate");
  assert.equal(manifest.license, "Apache-2.0");
  assert.equal(manifest.runtime.accelerator, "webgpu");
  assert.equal(manifest.files.reduce((sum, file) => sum + file.bytes, 0), 1241534740);
  assert.match(manifest.modelBase, /^\.\/moebius-/);
  assert.equal(manifest.upstream.onnxCommit, "5bf1ef5d2861ec01a727183a3f95dc64f352120e");
  const vendor = await readFile(join(root, "vendor/moebius-080be6e/moebius-pipeline.js"));
  assert.equal(createHash("sha256").update(vendor).digest("hex"), manifest.vendor.sha256);
  assert.match(vendor.toString(), /onnxruntime-web\/1\.27\.0\/ort\.webgpu\.min\.mjs/);
});

test("quality reconstruction gives selected objects broad bounded scene context", () => {
  const landscape = planQualitySceneCrop([
    { box: { x: 486, y: 274, width: 308, height: 165 } },
    { box: { x: 971, y: 379, width: 152, height: 154 } },
    { box: { x: 699, y: 293, width: 125, height: 281 } }
  ], { width: 1280, height: 720 });
  assert.deepEqual(landscape, { x: 445, y: 0, width: 720, height: 720 });

  const portrait = planQualitySceneCrop([
    { box: { x: 48, y: 167, width: 52, height: 57 } },
    { box: { x: 111, y: 688, width: 48, height: 50 } },
    { box: { x: 381, y: 315, width: 59, height: 176 } }
  ], { width: 600, height: 800 });
  assert.deepEqual(portrait, { x: 0, y: 153, width: 600, height: 600 });
});

test("quality reconstruction masks object footprints without expanding watermark geometry", () => {
  const crop = { x: 0, y: 100, width: 600, height: 600 };
  const [object, watermark] = planQualityMaskRegions([
    { label: "bag", box: { x: 120, y: 200, width: 60, height: 100 } },
    { label: "watermark logo", box: { x: 240, y: 240, width: 120, height: 60 } }
  ], crop);
  assert.ok(object.height > 100 / 600 * 512);
  assert.ok(object.width > 60 / 600 * 512);
  assert.ok(watermark.height < object.height);
});

test("vendored LiteRT packages are pinned and excluded from launcher imports", async () => {
  const vendor = JSON.parse(await read("vendor/litertjs/vendor-manifest.json"));
  assert.deepEqual(vendor.packages.map((item) => item.version), ["2.5.3", "2.5.3"]);
  assert.ok(vendor.packages.every((item) => item.integrity.startsWith("sha512-")));
  const launcher = await read("property-photo-cleaner.launcher.js");
  assert.doesNotMatch(launcher, /vendor\/litertjs|loadLiteRt|litert_wasm/);
});

test("runtime loader imports and initializes LiteRT only inside the AI loader", async () => {
  const source = await read("modules/runtime-loader.js");
  const functionIndex = source.indexOf("export async function loadVerifiedLiteRt");
  assert.ok(functionIndex >= 0);
  assert.ok(source.indexOf("import(moduleUrl)") > functionIndex);
  assert.ok(source.indexOf("loadLiteRt(wasmBase)") > functionIndex);
});

test("AI session loads LiteRT before enforcing the model admission gate", async () => {
  const source = await read("modules/inpainting-runtime.js");
  assert.ok(source.indexOf("loadVerifiedLiteRt") < source.indexOf('manifest.model?.status !== "verified"'));
});

test("fixture manifest identifies both reference pairs without embedding bytes", async () => {
  const text = await read("fixtures/fixture-manifest.json");
  const fixture = JSON.parse(text);
  assert.equal(fixture.pairs.length, 2);
  assert.doesNotMatch(text, /base64|data:image/i);
});

test("reference object inventory makes both visual acceptance targets explicit", async () => {
  const inventory = JSON.parse(await read("fixtures/object-inventory.json"));
  assert.equal(inventory.fixtures["visao_before1.jpeg"].length, 10);
  assert.equal(inventory.fixtures["visao_before2.jpeg"].length, 14);
  assert.match(inventory.scope, /authorized watermark layer/);
});

test("low-memory tile plan is sequential and bounded", () => {
  const tiles = planTiles({ x: 0, y: 0, width: 900, height: 700 }, { lowMemory: true });
  assert.ok(tiles.length > 1);
  assert.ok(tiles.every((tile) => tile.width <= 256 && tile.height <= 256));
});

test("correction values are deterministic", () => {
  assert.deepEqual(correctionValues({}), correctionValues({}));
  assert.equal(correctionValues({ brightness: 12 }).brightness, 12);
});

test("object detections have stable bounded model-facing boxes", () => {
  const detections = normalizeDetections([
    { label: "chair", score: 0.91234, box: { xmin: -2, ymin: 10, xmax: 52, ymax: 80 } },
    { label: "bag", score: 0.81, box: { xmin: 90, ymin: 90, xmax: 200, ymax: 200 } }
  ], { width: 100, height: 100 });
  assert.deepEqual(detections, [
    { id: "object-1", label: "chair", rawLabel: "chair", score: 0.912, source: "full", recovery: false, maskDescriptor: null, box: { x: 0, y: 10, width: 52, height: 70 } },
    { id: "object-2", label: "bag", rawLabel: "bag", score: 0.81, source: "full", recovery: false, maskDescriptor: null, box: { x: 90, y: 90, width: 10, height: 10 } }
  ]);
});

test("detection model is local, immutable, lazy, and honestly scoped", async () => {
  const manifest = JSON.parse(await read("models/detection-manifest.json"));
  assert.equal(manifest.status, "candidate");
  assert.equal(manifest.model.vocabulary, "property-cleanup-v1");
  assert.equal(manifest.model.revision, "v8.4.0");
  const bytes = await readFile(join(root, "models/yoloe-26s-property/yoloe-26s-property.onnx"));
  assert.equal(bytes.byteLength, manifest.model.bytes);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), manifest.model.sha256);
  const entry = await read("property-photo-cleaner.entry.js");
  assert.doesNotMatch(entry.split("export async function mount")[0], /findObjects\(/);
});

test("overlap suppression keeps the strongest box and stable ids", () => {
  const detections = suppressOverlaps([
    { id: "a", label: "bag", score: 0.8, box: { x: 0, y: 0, width: 50, height: 50 } },
    { id: "b", label: "backpack", score: 0.9, box: { x: 2, y: 2, width: 50, height: 50 } },
    { id: "c", label: "chair", score: 0.7, box: { x: 80, y: 80, width: 10, height: 10 } }
  ], 0.55);
  assert.deepEqual(detections.map(({ id, label }) => ({ id, label })), [
    { id: "object-1", label: "backpack" },
    { id: "object-2", label: "chair" }
  ]);
});

test("YOLOE output adapter maps end-to-end letterboxed boxes into source-image coordinates", () => {
  const results = decodeYoloEOutputs({
    dims: [1, 1, 6],
    data: new Float32Array([256, 288, 384, 352, 0.9, 0])
  }, ["ladder", "bag"], {
    threshold: 0.5,
    topK: 10,
    maxSceneAreaRatio: 0.25,
    maxWidthHeightRatio: 5
  }, { width: 100, height: 200 }, { scale: 3.2, offsetX: 160, offsetY: 0 });
  assert.equal(results.length, 1);
  assert.equal(results[0].label, "ladder");
  assert.deepEqual(results[0].box, { xmin: 30, ymin: 90, xmax: 70, ymax: 110 });
});

test("rectangular photos receive one full and two bounded detail views", () => {
  const profile = { detailViews: true, detailViewAspectRatio: 1.25 };
  assert.deepEqual(planDetectionViews(1270, 704, profile), [
    { x: 0, y: 0, width: 1270, height: 704, kind: "full" },
    { x: 0, y: 0, width: 704, height: 704, kind: "detail" },
    { x: 566, y: 0, width: 704, height: 704, kind: "detail" }
  ]);
});

test("moderate vertical detail proposals are exposed honestly as generic objects", () => {
  const results = decodeYoloEOutputs({
    dims: [1, 1, 6],
    data: new Float32Array([100, 100, 180, 250, 0.055, 0])
  }, ["chair"], {
    threshold: 0.06,
    detailThreshold: 0.05,
    topK: 10,
    maxSceneAreaRatio: 0.25,
    maxWidthHeightRatio: 5,
    detailStrongThreshold: 0.12,
    detailMinAreaRatio: 0.001,
    detailMaxAreaRatio: 0.006,
    detailModerateThreshold: 0.05,
    detailModerateMinAreaRatio: 0.006,
    detailModerateMaxAreaRatio: 0.05,
    detailModerateMaxWidthHeightRatio: 1.5,
    boundaryMarginRatio: 0.01,
    maxBoundaryPartialAreaRatio: 0.03,
    fullSmallStrongThreshold: 0.12,
    fullSmallMinAreaRatio: 0.001
  }, { width: 640, height: 640 }, { scale: 1, offsetX: 0, offsetY: 0 }, "detail");
  assert.equal(results[0].label, "object");
  assert.equal(results[0].rawLabel, "chair");
});

test("compact low-confidence floor proposals recover honestly without widening scene thresholds", () => {
  const profile = {
    threshold: 0.02,
    topK: 10,
    maxSceneAreaRatio: 0.25,
    maxWidthHeightRatio: 5,
    boundaryMarginRatio: 0.01,
    maxBoundaryPartialAreaRatio: 0.03,
    fullSmallStrongThreshold: 0.12,
    fullSmallMinAreaRatio: 0.001,
    fullLowConfidenceThreshold: 0.06,
    fullLowConfidenceMaxAreaRatio: 0.01,
    fullLowConfidenceMaxWidthHeightRatio: 1.5,
    fullLowConfidenceMinCenterYRatio: 0.7
  };
  const recovered = decodeYoloEOutputs({
    dims: [1, 1, 6],
    data: new Float32Array([96, 618, 155, 665, 0.023, 0])
  }, ["rolled carpet"], profile, { width: 600, height: 800 }, { scale: 1, offsetX: 0, offsetY: 0 });
  assert.equal(recovered[0].label, "object");
  assert.equal(recovered[0].rawLabel, "rolled carpet");
  assert.equal(recovered[0].recovery, true);

  const wideStrip = decodeYoloEOutputs({
    dims: [1, 1, 6],
    data: new Float32Array([405, 628, 575, 670, 0.027, 0])
  }, ["rolled carpet"], profile, { width: 1280, height: 720 }, { scale: 1, offsetX: 0, offsetY: 0 });
  assert.equal(wideStrip.length, 0);
});

test("watermark evidence requires both warm and cool chroma", () => {
  const watermark = { minimumChroma: 18, minimumWarmRatio: 0.2, minimumCoolRatio: 0.2 };
  const paired = new Uint8ClampedArray([
    210, 110, 120, 255,
    90, 170, 205, 255,
    150, 150, 150, 255,
    150, 150, 150, 255
  ]);
  assert.equal(hasWatermarkChromaEvidence(paired, 4, watermark).matched, true);
  const warmOnly = new Uint8ClampedArray([
    210, 110, 120, 255,
    210, 110, 120, 255,
    150, 150, 150, 255,
    150, 150, 150, 255
  ]);
  assert.equal(hasWatermarkChromaEvidence(warmOnly, 4, watermark).matched, false);
});

test("inpainting uses a bounded square context crop instead of shrinking the full photo", () => {
  assert.deepEqual(
    planInpaintingCrop(
      { x: 96, y: 618, width: 59, height: 47 },
      { width: 600, height: 800 }
    ),
    { x: 30, y: 546, width: 192, height: 192 }
  );
  const edgeCrop = planInpaintingCrop(
    { x: 0, y: 700, width: 80, height: 90 },
    { width: 600, height: 800 }
  );
  assert.equal(edgeCrop.x, 0);
  assert.equal(edgeCrop.y + edgeCrop.height, 800);
  assert.equal(edgeCrop.width, edgeCrop.height);
});

test("selected detections clean from smallest region to largest", () => {
  const ordered = orderDetectionsForCleaning([
    { id: "large", box: { width: 100, height: 100 } },
    { id: "small", box: { width: 20, height: 30 } }
  ]);
  assert.deepEqual(ordered.map((item) => item.id), ["small", "large"]);
});

test("large selections become bounded overlapping inpainting strokes", () => {
  const passes = planDetectionCleanPasses({
    id: "clothes",
    label: "hanging clothes",
    box: { x: 381, y: 316, width: 58, height: 174 }
  });
  assert.equal(passes.length, 4);
  assert.ok(passes.every((pass) => pass.box.width <= 64 && pass.box.height <= 64));
  assert.equal(passes[0].box.y, 316);
  assert.equal(passes.at(-1).box.y + passes.at(-1).box.height, 490);
});

test("review workflow exposes one clean button directly below object discovery", async () => {
  const html = await read("property-photo-cleaner.html");
  assert.match(html, /data-action="find_objects">Find objects<\/button>\s*<button[^>]+data-action="clean_objects">Clean objects now/);
  assert.match(html, /generative cleaning stay on this device/);
  assert.doesNotMatch(html, /data-cloud-confirm|sent to OpenAI/);
  assert.doesNotMatch(html, /Brush over an unwanted object|Remove brushed object/);
  const contract = await read("modules/status-contract.js");
  assert.match(contract, /"find_objects", "clean_objects", "undo_clean"/);
});

test("cleaning uses one lossless browser-local LaMa canvas and never uploads photo bytes", async () => {
  const source = await read("modules/local-object-cleaner.js");
  const worker = await read("workers/inference-worker.js");
  const entry = await read("property-photo-cleaner.entry.js");
  assert.match(source, /createLamaWorkerSession/);
  assert.match(source, /lama-256-places2\.onnx/);
  assert.match(source, /createDetectionMaskFrame/);
  assert.match(source, /inpaintLamaCanvas/);
  assert.match(source, /intermediateEncodingCount: 0/);
  assert.doesNotMatch(source, /image\/jpeg|0\.94/);
  assert.match(source, /sessionPromise/);
  assert.doesNotMatch(source, /fetch\(|api[_-]?key|authorization/i);
  assert.match(worker, /InferenceSession\.create/);
  assert.match(worker, /executionProviders: \["wasm"\]/);
  assert.match(entry, /cleanSelectedObjects\(current\.output \|\| current\.blob, selected/);
  assert.doesNotMatch(entry, /cloudAuthorized|networkUsedForPhoto = true/);
});

test("entry does not import workers, model bytes, fixtures, or ZIP at module evaluation", async () => {
  const source = await read("property-photo-cleaner.entry.js");
  assert.doesNotMatch(source, /workers\/|\.tflite|jszip|fflate/i);
  const files = await readdir(root);
  assert.ok(files.includes("property-photo-cleaner.launcher.js"));
});

test("opened-widget capability selection requires a real WebGPU device", async () => {
  const source = await read("property-photo-cleaner.entry.js");
  assert.match(source, /probeCapabilities\(\{ requestGpuDevice: true \}\)/);
  assert.match(source, /device\.device \? "webgpu"/);
});
