"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const http = require("node:http");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { chromium } = require("../../../tools/app-simulator/node_modules/playwright-core");

const publicRoot = path.resolve(__dirname, "..", "public");
const reportRoot = path.resolve(__dirname, "..", "..", "..", "reports", "sim", "browser-wasm-runtime", "latest");
const mime = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".wasm": "application/wasm" };

function chromiumPath() {
  for (const name of ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable"]) {
    const result = spawnSync("bash", ["-lc", `command -v ${name}`], { encoding: "utf8" });
    if (result.status === 0 && result.stdout.trim()) return result.stdout.trim();
  }
  return process.env.WASM_AGENT_SIM_CHROMIUM || "";
}

const server = http.createServer((request, response) => {
  const pathname = decodeURIComponent(new URL(request.url, "http://local").pathname);
  if (pathname === "/browser-navigation-fixture") {
    response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Access-Control-Allow-Origin": "*" });
    response.end("<!doctype html><head><title>Fetched Page</title><link rel=stylesheet href=/browser-style-fixture.css></head><main><h1>Network Navigation</h1><img src=/browser-image-fixture.png alt=Landscape><a href=/browser-second-fixture>Next page</a><form action=/browser-search-fixture><input name=q value=wasm><button>Search</button></form><p>Scrollable one</p><p>Scrollable two</p><p>Scrollable three</p><p>Scrollable four</p><p>Scrollable five</p></main>");
    return;
  }
  if (pathname === "/browser-style-fixture.css") {
    response.writeHead(200, { "Content-Type": "text/css", "Access-Control-Allow-Origin": "*" });
    response.end("main { background: #26384d; padding: 20px; } h1 { color: #ffffff; } a { background: #176b8a; color: #ffffff; } form { display: flex; gap: 10px; } button { background: #2186a8; color: #ffffff; }");
    return;
  }
  if (pathname === "/browser-image-fixture.png") {
    response.writeHead(200, { "Content-Type": "image/png", "Access-Control-Allow-Origin": "*" });
    response.end(Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=", "base64"));
    return;
  }
  if (pathname === "/browser-second-fixture") {
    response.writeHead(200, { "Content-Type": "text/html", "Access-Control-Allow-Origin": "*" });
    response.end("<title>Second Page</title><main><h1>Link worked</h1></main>");
    return;
  }
  if (pathname === "/browser-search-fixture") {
    response.writeHead(200, { "Content-Type": "text/html", "Access-Control-Allow-Origin": "*" });
    response.end(`<title>Search Page</title><main><h1>${new URL(request.url, "http://local").searchParams.get("q") || "empty"}</h1></main>`);
    return;
  }
  if (pathname === "/favicon.ico") {
    response.writeHead(204).end();
    return;
  }
  const target = path.resolve(publicRoot, `.${pathname}`);
  if (!target.startsWith(`${publicRoot}${path.sep}`) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
    response.writeHead(404).end("not found");
    return;
  }
  response.writeHead(200, { "Content-Type": mime[path.extname(target)] || "application/octet-stream", "Cache-Control": "no-store" });
  fs.createReadStream(target).pipe(response);
});

(async () => {
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const executablePath = chromiumPath();
  assert.ok(executablePath, "Chromium is required for the WASM browser runtime proof");
  const browser = await chromium.launch({ executablePath, headless: true, args: ["--no-sandbox", "--enable-unsafe-webgpu"] });
  try {
    const page = await browser.newPage();
    const runtimeErrors = [];
    page.on("pageerror", (error) => runtimeErrors.push(error.message));
    page.on("console", (message) => { if (message.type() === "error") runtimeErrors.push(message.text()); });
    await page.goto(`http://127.0.0.1:${server.address().port}/modules/browser/runtime/proof.html?renderer=canvas2d`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(() => window.browserRuntimeProof?.status !== "starting", null, { timeout: 10000 });
    const proof = await page.evaluate(() => window.browserRuntimeProof);
    assert.equal(proof.status, "ready", proof.message || "runtime did not become ready");
    assert.equal(proof.runtime, "direct-wasm-rust-v1");
    assert.equal(proof.renderer, "canvas2d-fallback");
    assert.deepEqual(proof.render_features, ["boxes", "canvas-text", "image-bitmaps"]);
    assert.equal(proof.token_count, 12);
    assert.equal(proof.elements.length, 6);
    assert.deepEqual(proof.elements.map((item) => item.role), ["main", "heading", "paragraph", "section", "button", "button"]);
    assert.deepEqual(proof.elements.slice(4).map((item) => item.parent), ["n4", "n4"]);
    assert.deepEqual(proof.elements.slice(4).map((item) => item.name), ["Inspect", "Navigate"]);
    assert.equal(proof.width, 640);
    assert.equal(proof.height, 360);
    assert.deepEqual(runtimeErrors, []);
    const remoteUrl = `http://127.0.0.1:${server.address().port}/browser-navigation-fixture`;
    await page.evaluate((url) => window.navigateBrowserRuntime(url), remoteUrl);
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, remoteUrl, { timeout: 10000 });
    const navigatedProof = await page.evaluate(() => window.browserRuntimeProof);
    assert.equal(navigatedProof.title, "Fetched Page");
    assert.equal(navigatedProof.requested_url, remoteUrl);
    assert.equal(navigatedProof.navigation.source, "network");
    assert.deepEqual(navigatedProof.elements.slice(0, 7).map(({ role, name }) => [role, name]), [["main", ""], ["heading", "Network Navigation"], ["image", "Landscape"], ["link", "Next page"], ["form", ""], ["textbox", "wasm"], ["button", "Search"]]);
    assert.equal(navigatedProof.resources.stylesheets[0].status, "loaded");
    assert.equal(navigatedProof.resources.images[0].status, "loaded", JSON.stringify(navigatedProof.resources.images[0]));
    assert.equal(navigatedProof.navigation.can_go_back, true);
    const link = navigatedProof.elements.find((element) => element.role === "link");
    await page.evaluate(({ x, y }) => window.inputBrowserRuntime({ input: "pointerdown", x, y }), { x: link.bounds[0] + 4, y: link.bounds[1] + 4 });
    const secondUrl = `http://127.0.0.1:${server.address().port}/browser-second-fixture`;
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, secondUrl, { timeout: 10000 });
    await page.evaluate(() => window.actionBrowserRuntime("back"));
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, remoteUrl, { timeout: 10000 });
    const extensionUrl = "https://www.google.com/";
    await page.evaluate((url) => {
      window.browserExtensionFixture = { url, html: "<title>Extension Page</title><main><h1>Extension bridge worked</h1></main>" };
      window.navigateBrowserRuntime("http://127.0.0.1:1/native-fetch-must-fail");
    }, extensionUrl);
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, extensionUrl, { timeout: 10000 });
    const extensionProof = await page.evaluate(() => window.browserRuntimeProof);
    assert.equal(extensionProof.resources.document.transport, "chrome-extension-v1");
    assert.equal(extensionProof.elements[1].name, "Extension bridge worked");
    assert.match(extensionProof.resources.document.sha256, /^[a-f0-9]{64}$/);
    await page.evaluate(() => { delete window.browserExtensionFixture; window.actionBrowserRuntime("back"); });
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, remoteUrl, { timeout: 10000 });
    const restoredProof = await page.evaluate(() => window.browserRuntimeProof);
    assert.ok(restoredProof.interaction.max_scroll_y > 0);
    await page.evaluate(() => window.inputBrowserRuntime({ input: "wheel", deltaY: 180 }));
    await page.waitForFunction(() => window.browserRuntimeProof?.interaction?.scroll_y > 0, null, { timeout: 10000 });
    await page.evaluate(() => window.inputBrowserRuntime({ input: "wheel", deltaY: -1000 }));
    await page.waitForFunction(() => window.browserRuntimeProof?.interaction?.scroll_y === 0, null, { timeout: 10000 });
    const textbox = restoredProof.elements.find((element) => element.role === "textbox");
    await page.evaluate(({ x, y }) => window.inputBrowserRuntime({ input: "pointerdown", x, y }), { x: textbox.bounds[0] + textbox.bounds[2] - 8, y: textbox.bounds[1] + 4 });
    for (const key of "-agent") await page.evaluate((value) => window.inputBrowserRuntime({ input: "keydown", key: value }), key);
    await page.waitForFunction(() => window.browserRuntimeProof?.elements?.find((element) => element.role === "textbox")?.name === "wasm-agent", null, { timeout: 10000 });
    await page.evaluate(() => window.inputBrowserRuntime({ input: "keydown", key: "ArrowLeft", shiftKey: true }));
    await page.evaluate(() => window.inputBrowserRuntime({ input: "keydown", key: "ArrowLeft", shiftKey: true }));
    await page.waitForFunction(() => Math.abs(window.browserRuntimeProof.interaction.selection_end - window.browserRuntimeProof.interaction.selection_start) === 2, null, { timeout: 10000 });
    await page.evaluate(() => window.inputBrowserRuntime({ input: "keydown", key: "End" }));
    await page.evaluate(() => window.inputBrowserRuntime({ input: "keydown", key: "Enter" }));
    const searchUrl = `http://127.0.0.1:${server.address().port}/browser-search-fixture?q=wasm-agent`;
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, searchUrl, { timeout: 10000 });
    await page.evaluate(() => window.actionBrowserRuntime("back"));
    await page.waitForFunction((url) => window.browserRuntimeProof?.url === url, remoteUrl, { timeout: 10000 });
    fs.mkdirSync(reportRoot, { recursive: true });
    await page.waitForTimeout(250);
    await page.screenshot({ path: path.join(reportRoot, "final.png") });
    await page.locator("#browser").screenshot({ path: path.join(reportRoot, "canvas.png") });
    fs.writeFileSync(path.join(reportRoot, "proof.json"), JSON.stringify({
      ...navigatedProof,
      extension_fallback: { url: extensionProof.url, title: extensionProof.title, document: extensionProof.resources.document },
      runtime_errors: runtimeErrors,
    }, null, 2));
    console.log(`browser WASM runtime navigation proof passed (${navigatedProof.renderer})`);
  } finally {
    await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
})().catch((error) => {
  server.close();
  console.error(error);
  process.exitCode = 1;
});
