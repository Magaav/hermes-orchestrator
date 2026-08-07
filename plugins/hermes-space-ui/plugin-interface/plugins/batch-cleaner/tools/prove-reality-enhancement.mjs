import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const toolRoot = dirname(fileURLToPath(import.meta.url));
const pluginRoot = resolve(toolRoot, "..");
const inputPath = process.env.REALITY_INPUT
  || "/tmp/property-photo-cleaner-visao-before2-cleaned-lama-256-targets-v2.png";
const outputRoot = process.env.REALITY_OUTPUT_ROOT || "/tmp/batch-cleaner/reality";
const chromiumPath = process.env.BATCH_CHROMIUM_PATH || "/usr/bin/chromium-browser";
const mime = {
  ".css": "text/css",
  ".html": "text/html",
  ".js": "text/javascript",
  ".mjs": "text/javascript",
  ".png": "image/png"
};
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    if (pathname === "/") {
      response.setHeader("Content-Type", "text/html");
      response.end("<!doctype html><html><body></body></html>");
      return;
    }
    if (pathname === "/input.png") {
      response.setHeader("Content-Type", "image/png");
      response.end(await readFile(inputPath));
      return;
    }
    const file = resolve(pluginRoot, `.${pathname}`);
    if (!file.startsWith(`${pluginRoot}/`)) throw new Error("outside plugin");
    response.setHeader("Content-Type", mime[extname(file)] || "application/octet-stream");
    response.end(await readFile(file));
  } catch {
    response.statusCode = 404;
    response.end("Not found");
  }
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));

const { chromium } = (await import("/local/tools/app-simulator/node_modules/playwright-core/index.js")).default;
const browser = await chromium.launch({ executablePath: chromiumPath, headless: true });
let evidence;
try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  evidence = await page.evaluate(async () => {
    const { enhanceReality } = await import("/modules/reality-enhancer.js");
    const source = await fetch("/input.png").then((response) => response.blob());
    const result = await enhanceReality(source);
    async function pixels(blob) {
      const bitmap = await createImageBitmap(blob);
      const canvas = new OffscreenCanvas(bitmap.width, bitmap.height);
      const context = canvas.getContext("2d", { alpha: false, willReadFrequently: true });
      context.drawImage(bitmap, 0, 0);
      bitmap.close();
      return {
        width: canvas.width,
        height: canvas.height,
        data: context.getImageData(0, 0, canvas.width, canvas.height).data
      };
    }
    function metrics(frame) {
      const light = new Float32Array(frame.width * frame.height);
      let sum = 0;
      let sumSquares = 0;
      let clipped = 0;
      for (let index = 0, pixel = 0; pixel < light.length; pixel += 1, index += 4) {
        const value = frame.data[index] * 0.2126 + frame.data[index + 1] * 0.7152 + frame.data[index + 2] * 0.0722;
        light[pixel] = value;
        sum += value;
        sumSquares += value * value;
        if (value <= 2 || value >= 253) clipped += 1;
      }
      let laplacian = 0;
      let laplacianSquares = 0;
      let laplacianCount = 0;
      for (let y = 1; y < frame.height - 1; y += 1) {
        for (let x = 1; x < frame.width - 1; x += 1) {
          const pixel = y * frame.width + x;
          const value = light[pixel] * 4 - light[pixel - 1] - light[pixel + 1]
            - light[pixel - frame.width] - light[pixel + frame.width];
          laplacian += value;
          laplacianSquares += value * value;
          laplacianCount += 1;
        }
      }
      const mean = sum / light.length;
      const laplacianMean = laplacian / laplacianCount;
      return {
        width: frame.width,
        height: frame.height,
        luminanceMean: mean,
        luminanceDeviation: Math.sqrt(sumSquares / light.length - mean * mean),
        laplacianVariance: laplacianSquares / laplacianCount - laplacianMean * laplacianMean,
        clippedRatio: clipped / light.length
      };
    }
    const [before, after] = await Promise.all([pixels(source), pixels(result.blob)]);
    return {
      profileId: result.profileId,
      scale: result.scale,
      before: metrics(before),
      after: metrics(after),
      output: Array.from(new Uint8Array(await result.blob.arrayBuffer()))
    };
  });
} finally {
  await browser.close();
  server.close();
}
await mkdir(outputRoot, { recursive: true });
const output = Uint8Array.from(evidence.output);
delete evidence.output;
const outputPath = resolve(outputRoot, "visao-before2-remastered.png");
await writeFile(outputPath, output);
evidence.outputPath = outputPath;
await writeFile(resolve(outputRoot, "evidence.json"), `${JSON.stringify(evidence, null, 2)}\n`);
console.log(JSON.stringify(evidence, null, 2));
