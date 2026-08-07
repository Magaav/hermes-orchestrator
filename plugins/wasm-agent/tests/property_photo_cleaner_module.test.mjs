import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import test from "node:test";

const root = new URL("../", import.meta.url).pathname;
const read = (path, encoding = "utf8") => readFile(join(root, path), encoding);

test("property photo cleaner is mapped through the generic lazy app registry", async () => {
  const registry = await read("public/modules/app-registry.js");
  const shell = await read("public/app.js");
  assert.match(registry, /id: "property-photo-cleaner"/);
  assert.match(registry, /entry: "\/modules\/property-photo-cleaner\/property-photo-cleaner\.entry\.js"/);
  assert.match(registry, /import\(app\.entry\)/);
  assert.match(shell, /openExternalAppFromIcon/);
  assert.match(registry, /ensureExternalAppMounted\(app\)/);
  assert.doesNotMatch(shell, /migan|litert|property-photo-cleaner\.entry/);
});

test("startup cache excludes the photo cleaner runtime, model, and fixtures", async () => {
  const serviceWorker = await read("public/sw.js");
  assert.doesNotMatch(serviceWorker, /property-photo-cleaner|litert|migan|visao_/i);
});

test("admitted model bytes match the immutable manifest", async () => {
  const moduleRoot = "public/modules/property-photo-cleaner";
  const manifest = JSON.parse(await read(`${moduleRoot}/models/model-manifest.json`));
  const modelPath = manifest.model.url.replace(/^\.\.\//, "");
  const bytes = await read(`${moduleRoot}/${modelPath}`, null);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), manifest.model.sha256);
  assert.equal(manifest.runtime.id, "onnxruntime-web");
  assert.equal(manifest.model.id, "big-lama-256-places2");
  assert.equal(manifest.status, "browser_wasm_fixture_verified");
  assert.equal(manifest.model.status, "verified");
  assert.equal(manifest.admission.status, "verified_baseline");
  assert.equal(manifest.candidates[0].status, "rejected_quality");
  assert.equal(manifest.candidates[0].failureClass, "semantic_reconstruction_failure");
  assert.equal(manifest.verification.photoNetworkWrites, 0);
});

test("model admission requires reference parity and rejects black patches", async () => {
  const gate = await read("public/modules/property-photo-cleaner/modules/reconstruction-quality-gate.js");
  assert.match(gate, /catastrophic_black_patch/);
  assert.match(gate, /maximumNearBlackRatio/);
  const pipeline = await read("public/modules/property-photo-cleaner/modules/migan-pipeline.js");
  assert.match(pipeline, /assertGeneratedPatch/);
  const proof = await read("public/modules/property-photo-cleaner/models/tools/prove-litert-parity.mjs");
  assert.match(proof, /knownRegionMaxDelta === 0/);
  assert.match(proof, /maskedRegionMaxDelta <= 2/);
  assert.match(proof, /modelSha256 === manifest\.model\.sha256/);
});

test("photo processing module keeps photo bytes browser-local", async () => {
  const definition = await read("public/modules/property-photo-cleaner/module.js");
  assert.match(definition, /endpoints: \[\]/);
  const entry = await read("public/modules/property-photo-cleaner/property-photo-cleaner.entry.js");
  assert.match(entry, /cleanSelectedObjects/);
  const cleaner = await read("public/modules/property-photo-cleaner/modules/local-object-cleaner.js");
  assert.match(cleaner, /createLamaWorkerSession/);
  assert.match(cleaner, /inpaintLamaCanvas/);
  assert.match(cleaner, /createDetectionMaskFrame\(cleaned, detections\[index\]\)/);
  assert.match(cleaner, /session\?\.dispose\(\)/);
  assert.match(cleaner, /requestAnimationFrame/);
  assert.doesNotMatch(cleaner, /createInpaintingSession|inpaintMigan/);
  const inpaintingRuntime = await read("public/modules/property-photo-cleaner/modules/onnx-inpainting-runtime.js");
  assert.match(inpaintingRuntime, /new Worker/);
  assert.match(inpaintingRuntime, /request\("run"/);
  const client = await read("public/modules/property-photo-cleaner/modules/cloud-object-cleaner.js");
  assert.match(client, /method: "POST"/);
  assert.doesNotMatch(client, /api[_-]?key|authorization/i);
});

test("batch cleaning uses the verified local baseline and remains background-safe", async () => {
  const entry = await read("public/modules/batch-cleaner/batch-cleaner.entry.js");
  const html = await read("public/modules/batch-cleaner/batch-cleaner.html");
  assert.match(entry, /local-object-cleaner\.js\?v=20260727-lama-baseline1/);
  assert.match(entry, /continuing with the verified local baseline/);
  assert.match(entry, /Scene-aware reconstruction unavailable/);
  assert.match(entry, /reconstructionStrategy: item\.reconstructionStrategy/);
  assert.match(entry, /segmentedDetections: item\.segmentedDetections/);
  assert.doesNotMatch(entry, /continuing locally with LiteRT/);
  assert.match(html, /data-quality-reconstruction checked/);
  assert.match(html, /1\.24 GB model once and may take 2–3 minutes/);
  assert.doesNotMatch(html, /standard LiteRT|local LiteRT/);
  assert.doesNotMatch(entry, /requestAnimationFrame/);
});

test("closed object outlines fill the selected region before inference", async () => {
  const editor = await read("public/modules/property-photo-cleaner/modules/mask-editor.js");
  assert.match(editor, /points\.length >= 3/);
  assert.match(editor, /maskContext\.closePath\(\)/);
  assert.match(editor, /maskContext\.fill\(\)/);
});

test("local object detection delivery is immutable and exposes bounded boxes", async () => {
  const moduleRoot = "public/modules/property-photo-cleaner";
  const manifest = JSON.parse(await read(`${moduleRoot}/models/detection-manifest.json`));
  const bytes = await read(`${moduleRoot}/models/yoloe-26s-property/yoloe-26s-property.onnx`, null);
  assert.equal(createHash("sha256").update(bytes).digest("hex"), manifest.model.sha256);
  assert.equal(manifest.model.vocabulary, "property-cleanup-v1");
  assert.equal(manifest.runtime.version, "1.27.0");
  const overlay = await read(`${moduleRoot}/modules/detection-overlay.js`);
  assert.match(overlay, /detection\.box/);
  assert.match(overlay, /onRemoveIntent/);
  const watermark = await read(`${moduleRoot}/modules/watermark-recognizer.js`);
  assert.match(watermark, /instanceMask/);
  const queue = await read("public/modules/batch-cleaner/modules/batch-queue.js");
  assert.match(queue, /!detection\.partial/);
});
