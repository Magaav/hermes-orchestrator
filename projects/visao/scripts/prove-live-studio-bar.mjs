#!/usr/bin/env node
// Authenticated responsive overflow proof for the Studio footer bar.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdp = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const url = new URL(process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/");
url.searchParams.set("studio-bar-proof", String(Date.now()));

const created = await fetch(`${cdp}/json/new?${encodeURIComponent(url)}`, { method: "PUT" });
if (!created.ok) throw new Error(`CDP target creation failed: HTTP ${created.status}`);
const target = await created.json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let id = 0;

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const current = ++id;
    pending.set(current, { resolve, reject });
    socket.send(JSON.stringify({ id: current, method, params }));
  });
}

socket.on("message", (wire) => {
  const message = JSON.parse(String(wire));
  const waiter = pending.get(message.id);
  if (!waiter) return;
  pending.delete(message.id);
  if (message.error) waiter.reject(new Error(message.error.message));
  else waiter.resolve(message.result || {});
});
await new Promise((resolve, reject) => {
  socket.once("open", resolve);
  socket.once("error", reject);
});

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text);
  return result.result?.value;
}

async function waitFor(expression) {
  const deadline = Date.now() + 45_000;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 150));
  }
  throw new Error(`Timed out: ${expression}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Page.navigate", { url: String(url) });
  await waitFor("document.readyState === 'complete' && !!document.querySelector('.home')");
  await evaluate(`[...document.querySelectorAll(".module-card")].find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  await waitFor("!!document.querySelector('.studio-bar')");

  const results = [];
  for (const width of [1280, 800, 390, 320]) {
    await command("Emulation.setDeviceMetricsOverride", { width, height: 800, deviceScaleFactor: 1, mobile: width <= 390 });
    await new Promise((resolve) => setTimeout(resolve, 100));
    results.push(await evaluate(`(() => {
      const bar = document.querySelector(".studio-bar");
      const inner = document.querySelector(".studio-bar__inner");
      const actions = document.querySelector(".studio-bar__actions");
      return {
        width: ${width},
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        barOverflow: bar.scrollWidth - bar.clientWidth,
        innerOverflow: inner.scrollWidth - inner.clientWidth,
        actionsOverflow: actions.scrollWidth - actions.clientWidth
      };
    })()`));
  }

  await command("Emulation.setDeviceMetricsOverride", { width: 390, height: 800, deviceScaleFactor: 1, mobile: true });
  const capture = await command("Page.captureScreenshot", { format: "png" });
  const screenshotPath = "/tmp/visao-studio-bar-mobile.png";
  await fs.writeFile(screenshotPath, Buffer.from(capture.data, "base64"));
  const ok = results.every((result) => Object.entries(result).every(([key, value]) => key === "width" || value === 0));
  process.stdout.write(`${JSON.stringify({ ok, results, screenshotPath })}\n`);
  if (!ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdp}/json/close/${target.id}`).catch(() => undefined);
}
