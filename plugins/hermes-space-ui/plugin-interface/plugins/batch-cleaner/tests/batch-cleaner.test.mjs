import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import {
  acceptedBatchFiles,
  batchSummary,
  canCleanBatch,
  cleanedFilename,
  cleanableDetections,
  MAX_BATCH_PHOTOS
} from "../modules/batch-queue.js";
import { createZip } from "../modules/zip-export.js";
import {
  enhancementDimensions,
  enhanceRealityPixels,
  REALITY_ENHANCEMENT_PROFILE
} from "../modules/reality-enhancement.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFile(join(root, path), "utf8");

test("batch admission accepts only images and caps the queue at 30", () => {
  const files = Array.from({ length: 35 }, (_, index) => ({
    name: `${index}.jpg`,
    type: index === 2 ? "text/plain" : "image/jpeg"
  }));
  const accepted = acceptedBatchFiles(files, 0);
  assert.equal(MAX_BATCH_PHOTOS, 30);
  assert.equal(accepted.length, 30);
  assert.ok(accepted.every((file) => file.type.startsWith("image/")));
  assert.equal(acceptedBatchFiles(files, 29).length, 1);
});

test("clean all waits for every included photo and ignores excluded photos", () => {
  const items = [
    { included: true, state: "ready" },
    { included: true, state: "ready" },
    { included: false, state: "detecting" }
  ];
  assert.equal(canCleanBatch(items), true);
  items[1].state = "detecting";
  assert.equal(canCleanBatch(items), false);
  assert.deepEqual(batchSummary(items), {
    total: 3,
    included: 2,
    excluded: 1,
    detecting: 1,
    ready: 1,
    cleaning: 0,
    cleaned: 0,
    failed: 0
  });
});

test("automatic cleaning uses the declared protected-label policy", () => {
  const item = {
    cleaningPolicy: { protectedLabels: ["desk"] },
    detections: [{ label: "desk" }, { label: "shoes" }, { label: "watermark logo" }]
  };
  assert.deepEqual(cleanableDetections(item).map((item) => item.label), ["shoes", "watermark logo"]);
});

test("cleaned filenames are stable and filesystem safe", () => {
  assert.equal(cleanedFilename('room:one?.jpeg', 2), "03-room-one--cleaned.jpeg");
});

test("ZIP export creates a valid uncompressed archive envelope", async () => {
  const zip = await createZip([
    { name: "one.jpg", blob: new Blob(["one"]) },
    { name: "two.jpg", blob: new Blob(["two"]) }
  ]);
  const bytes = new Uint8Array(await zip.arrayBuffer());
  const view = new DataView(bytes.buffer);
  assert.equal(view.getUint32(0, true), 0x04034b50);
  assert.equal(view.getUint32(bytes.length - 22, true), 0x06054b50);
  assert.equal(view.getUint16(bytes.length - 14, true), 2);
});

test("reality enhancement increases bounded micro-contrast without clipping the frame", () => {
  const width = 24;
  const height = 16;
  const pixels = new Uint8ClampedArray(width * height * 4);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 4;
      const value = x < width / 2 ? 108 : 138;
      pixels[index] = value;
      pixels[index + 1] = value + 2;
      pixels[index + 2] = value + 4;
      pixels[index + 3] = 255;
    }
  }
  const enhanced = enhanceRealityPixels(pixels, width, height);
  const left = enhanced[((height / 2) * width + width / 2 - 1) * 4];
  const right = enhanced[((height / 2) * width + width / 2) * 4];
  assert.ok(right - left > 30);
  assert.ok(Math.max(...enhanced.filter((_, index) => index % 4 !== 3)) < 255);
  assert.ok(Math.min(...enhanced.filter((_, index) => index % 4 !== 3)) > 0);
});

test("reality enhancement raises density by 1.25x without downscaling large originals", () => {
  assert.deepEqual(enhancementDimensions(800, 600), { width: 1000, height: 750, scale: 1.25 });
  const bounded = enhancementDimensions(6000, 4000);
  assert.equal(bounded.width, 6000);
  assert.equal(bounded.height, 4000);
  assert.equal(bounded.scale, 1);
  assert.equal(REALITY_ENHANCEMENT_PROFILE.maximumPixels, 12_000_000);
});

test("widget exposes the requested grid, queue overlays, clean all, preview, and export all", async () => {
  const [html, css, entry] = await Promise.all([
    read("batch-cleaner.html"),
    read("batch-cleaner.css"),
    read("batch-cleaner.entry.js")
  ]);
  assert.match(html, /data-drop-zone/);
  assert.match(html, /data-action="clean_all">Clean all/);
  assert.match(html, /data-action="export_all">Export all/);
  assert.match(html, /data-quality-reconstruction/);
  assert.match(html, /scene-aware WebGPU cleaning/);
  assert.match(html, /data-cloud-quality/);
  assert.match(html, /Perfect reconstruction/);
  assert.match(html, /data-enhance-reality/);
  assert.match(html, /data-preview/);
  assert.match(css, /\.bc-grid[^{]*\{[^}]*gap:\s*5px/s);
  assert.match(css, /\.bc-card[^{]*\{[^}]*aspect-ratio:\s*1/s);
  assert.match(entry, /findObjects/);
  assert.match(entry, /cleanSelectedObjects/);
  assert.match(entry, /reconstructSelectedObjects/);
  assert.match(entry, /cleanWithCloudQuality/);
  assert.match(entry, /enhanceReality/);
  assert.match(entry, /data-widget-control="maximize"/);
  assert.doesNotMatch(entry, /api[_-]?key|property-photo-cleaner\/edit/i);
});

test("bundle stays lazy and does not duplicate model assets", async () => {
  const [launcher, files] = await Promise.all([
    read("batch-cleaner.launcher.js"),
    import("node:fs/promises").then(({ readdir }) => readdir(root, { recursive: true }))
  ]);
  assert.match(launcher, /import\("\.\/batch-cleaner\.entry\.js\?v=0\.3\.0"\)/);
  assert.doesNotMatch(launcher, /onnxruntime|object-detector|local-object-cleaner/);
  assert.equal(files.some((file) => /\.(onnx|tflite|wasm)$/i.test(file)), false);
});
