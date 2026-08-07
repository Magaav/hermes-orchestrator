import { createServer } from "node:http";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const toolRoot = dirname(fileURLToPath(import.meta.url));
const modulesRoot = process.env.BATCH_MODULES_ROOT
  ? resolve(process.env.BATCH_MODULES_ROOT)
  : resolve(toolRoot, "../../../../../wasm-agent/public/modules");
const fixture = resolve(modulesRoot, "property-photo-cleaner/media/visao_before2.jpeg");
const chromiumPath = process.env.BATCH_CHROMIUM_PATH
  || "/home/ubuntu/.cache/ms-playwright/chromium-1228/chrome-linux/chrome";
const evidencePath = process.env.BATCH_EVIDENCE_PATH
  || "/tmp/batch-cleaner/browser-proof.json";
const screenshotPath = process.env.BATCH_SCREENSHOT_PATH
  || "/tmp/batch-cleaner/browser-proof.png";
const { chromium } = (await import("/local/tools/app-simulator/node_modules/playwright-core/index.js")).default;
const mime = {
  ".css": "text/css",
  ".html": "text/html",
  ".jpeg": "image/jpeg",
  ".js": "text/javascript",
  ".json": "application/json",
  ".mjs": "text/javascript",
  ".onnx": "application/octet-stream",
  ".svg": "image/svg+xml",
  ".wasm": "application/wasm"
};
const requests = [];
const server = createServer(async (request, response) => {
  try {
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    if (pathname === "/") {
      response.setHeader("Content-Type", "text/html");
      response.end("<!doctype html><html><head></head><body></body></html>");
      return;
    }
    const relativePath = pathname.startsWith("/modules/") ? pathname.slice("/modules/".length) : pathname.slice(1);
    const file = resolve(modulesRoot, relativePath);
    if (!file.startsWith(`${modulesRoot}/`)) throw new Error("outside modules root");
    requests.push({ method: request.method, path: pathname });
    response.setHeader("Content-Type", mime[extname(file)] || "application/octet-stream");
    response.setHeader("Cross-Origin-Opener-Policy", "same-origin");
    response.setHeader("Cross-Origin-Embedder-Policy", "require-corp");
    response.end(await readFile(file));
  } catch {
    response.statusCode = 404;
    response.end("Not found");
  }
});
await new Promise((ready) => server.listen(0, "127.0.0.1", ready));

const browser = await chromium.launch({
  executablePath: chromiumPath,
  headless: true,
  args: ["--enable-features=SharedArrayBuffer"]
});
let evidence;
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, acceptDownloads: true });
  const browserErrors = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  await page.evaluate(() => import("/modules/batch-cleaner/batch-cleaner.launcher.js")
    .then(async (module) => { globalThis.__batchProof = await module.batchCleaner.open(); }));
  await page.locator('input[type="file"]').setInputFiles([
    { name: "living-room.jpeg", mimeType: "image/jpeg", buffer: await readFile(fixture) },
    { name: "living-room-copy.jpeg", mimeType: "image/jpeg", buffer: await readFile(fixture) }
  ]);
  await page.locator(".bc-card").nth(1).waitFor();
  const queuedState = {
    cards: await page.locator(".bc-card").count(),
    workingOverlays: await page.locator(".bc-card-state:not([data-passive])").count(),
    ariaBusy: await page.locator("#batch-cleaner-root").getAttribute("aria-busy")
  };
  await page.locator(".bc-card").nth(1).locator(".bc-card-toggle").click();
  await page.waitForFunction(() => {
    const status = globalThis.__batchProof.inspectStatus();
    return (status.ready === 1 && status.excluded === 1) || status.failed > 0;
  }, null, { timeout: 120_000 });
  const readyState = await page.evaluate(() => globalThis.__batchProof.inspectStatus());
  if (readyState.failed) throw new Error(`Detection failed: ${JSON.stringify(readyState.photos)}`);
  const grid = await page.locator(".bc-grid").evaluate((element) => getComputedStyle(element).gap);
  const cardBox = await page.locator(".bc-card").first().boundingBox();
  await page.locator("[data-watermark-authorized]").check();
  await page.locator("[data-enhance-reality]").check();
  const startedAt = Date.now();
  await page.locator('[data-action="clean_all"]').click();
  await page.waitForFunction(() => globalThis.__batchProof.inspectStatus().cleaningRunning, null, { timeout: 10_000 });
  const cleaningState = {
    label: await page.locator(".bc-card").first().locator(".bc-card-state strong").textContent(),
    ariaBusy: await page.locator("#batch-cleaner-root").getAttribute("aria-busy")
  };
  await page.waitForFunction(() => globalThis.__batchProof.inspectStatus().cleaned === 1
    && !globalThis.__batchProof.inspectStatus().cleaningRunning, null, { timeout: 240_000 });
  await page.locator(".bc-card").first().click();
  await page.locator("[data-preview][open]").waitFor();
  const preview = {
    open: await page.locator("[data-preview]").evaluate((element) => element.open),
    cleanedEnabled: !(await page.locator('[data-action="preview_cleaned"]').isDisabled())
  };
  await page.locator('[data-action="close_preview"]').click();
  const downloadPromise = page.waitForEvent("download");
  await page.locator('[data-action="export_all"]').click();
  const download = await downloadPromise;
  await mkdir(dirname(evidencePath), { recursive: true });
  await page.screenshot({ path: screenshotPath });
  evidence = {
    schema: "hermes.batch_cleaner.browser_proof.v1",
    fixture: "visao_before2.jpeg",
    elapsedCleaningMs: Date.now() - startedAt,
    queuedState,
    readyState,
    layout: {
      gap: grid,
      squareDeltaPx: Math.abs(cardBox.width - cardBox.height)
    },
    cleaningState,
    finalState: await page.evaluate(() => globalThis.__batchProof.inspectStatus()),
    preview,
    download: download.suggestedFilename(),
    browserErrors,
    network: {
      nonGetRequests: requests.filter((request) => request.method !== "GET").length,
      modelGets: requests.filter((request) => request.path.endsWith(".onnx")).length
    },
    screenshotPath
  };
} finally {
  await browser.close();
  server.close();
}
await writeFile(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);
console.log(JSON.stringify(evidence, null, 2));
