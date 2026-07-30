#!/usr/bin/env node
// Authenticated, non-billable proof for Studio Codex access and AVIF delivery.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const appURL = process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/";
const assets = await fs.readdir(new URL("../frontend/dist/assets/", import.meta.url));
const workerAsset = assets.find((name) => /^avif\.worker-[\w-]+\.js$/.test(name));
if (!workerAsset) throw new Error("Built AVIF worker asset not found.");

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

const targetResponse = await fetch(`${cdpOrigin}/json/new?${encodeURIComponent(appURL)}`, { method: "PUT" });
if (!targetResponse.ok) throw new Error(`CDP target creation failed: HTTP ${targetResponse.status}`);
const target = await targetResponse.json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let requestID = 0;

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++requestID;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

socket.on("message", (wire) => {
  const message = JSON.parse(String(wire));
  if (!message.id || !pending.has(message.id)) return;
  const current = pending.get(message.id);
  pending.delete(message.id);
  if (message.error) current.reject(new Error(message.error.message || "CDP command failed"));
  else current.resolve(message.result || {});
});

await new Promise((resolve, reject) => {
  socket.once("open", resolve);
  socket.once("error", reject);
});

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
  return result.result?.value;
}

async function waitFor(expression, timeoutMilliseconds = 30_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await sleep(200);
  }
  throw new Error(`Browser condition timed out: ${expression.slice(0, 120)}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.enable");
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Page.navigate", { url: `${appURL}?studio-proof=${Date.now()}` });
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')");
  const homeReady = await evaluate(`!![...document.querySelectorAll("button")]
    .find((node) => /^studio/i.test((node.textContent || "").trim()))`);
  if (!homeReady) throw new Error("Authenticated Visão home is not available.");
  await evaluate(`[...document.querySelectorAll("button")]
    .find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  await waitFor("!!document.querySelector('[aria-label=\"Configurações do Studio\"]')");
  await evaluate("document.querySelector('[aria-label=\"Configurações do Studio\"]')?.click()");
  await waitFor("!!document.querySelector('.studio-settings') && !document.querySelector('.studio-access-loading')");

  const state = await evaluate(`Promise.all([
    fetch("/api/studio/status", { credentials: "same-origin" }).then((response) => response.json()),
    fetch("/api/studio/usage?period=month&scope=me&anchor=2026-07-30", { credentials: "same-origin" }).then((response) => response.json())
  ]).then(([status, usage]) => ({
    account: status.account,
    runtime: status.runtime,
    datacenter: status.datacenter,
    uiHasCodexRow: /conta codex/i.test(document.querySelector(".studio-settings")?.textContent || ""),
    uiHasNoAPIKey: !/chave de api|openai api/i.test(document.querySelector(".studio-settings")?.textContent || "")
      && !document.querySelector("#studio-openai-key"),
    summary: usage.summary
  }))`);
  await evaluate("document.querySelector('.studio-settings .module-back')?.click()");
  await waitFor("!!document.querySelector('[aria-label=\"Dashboard do Studio\"]')");
  await evaluate("document.querySelector('[aria-label=\"Dashboard do Studio\"]')?.click()");
  await waitFor("!!document.querySelector('.studio-dashboard') && !document.querySelector('.studio-dashboard__content.is-loading')");
  state.dashboard = await evaluate(`({
    completeKPI: /fotos com medi[cç][aã]o completa/i.test(document.querySelector(".studio-kpis")?.textContent || ""),
    partialNotice: !!document.querySelector(".studio-dashboard__partial"),
    points: document.querySelectorAll(".studio-chart__point").length
  })`);

  const avif = await evaluate(`new Promise((resolve, reject) => {
    const worker = new Worker(${JSON.stringify(`/assets/${workerAsset}`)}, { type: "module" });
    const values = [0, 64, 128, 255];
    const rgba = new Uint8ClampedArray(4 * 4 * 4);
    for (let index = 0; index < 16; index += 1) {
      const value = values[index % values.length];
      rgba.set([value, value, value, 255], index * 4);
    }
    const expected = Array.from(rgba);
    const timer = setTimeout(() => {
      worker.terminate();
      reject(new Error("AVIF worker timed out"));
    }, 30000);
    worker.onerror = () => {
      clearTimeout(timer);
      worker.terminate();
      reject(new Error("AVIF worker failed"));
    };
    worker.onmessage = async ({ data }) => {
      clearTimeout(timer);
      try {
        if (!data.ok || !data.buffer) throw new Error(data.error || "AVIF encode failed");
        const bytes = new Uint8Array(data.buffer);
        const brand = String.fromCharCode(...bytes.slice(4, 12));
        const blob = new Blob([data.buffer], { type: "image/avif" });
        const bitmap = await createImageBitmap(blob);
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const context = canvas.getContext("2d", { willReadFrequently: true });
        context.drawImage(bitmap, 0, 0);
        const decoded = context.getImageData(0, 0, bitmap.width, bitmap.height).data;
        bitmap.close();
        let maxChannelDelta = 0;
        for (let index = 0; index < decoded.length; index += 1) {
          maxChannelDelta = Math.max(maxChannelDelta, Math.abs(decoded[index] - expected[index]));
        }
        resolve({
          brand,
          bytes: blob.size,
          width: canvas.width,
          height: canvas.height,
          maxChannelDelta
        });
      } catch (error) {
        reject(error);
      } finally {
        worker.terminate();
      }
    };
    const pixels = new ImageData(rgba, 4, 4);
    worker.postMessage({ id: 1, imageData: pixels }, [pixels.data.buffer]);
  })`);

  const ok = state.account?.state === "connected"
    && state.runtime?.state === "ready"
    && state.datacenter?.state === "ready"
    && state.uiHasCodexRow
    && state.uiHasNoAPIKey
    && state.summary?.totalTokens === 0
    && state.summary?.partialPictures > 0
    && state.dashboard?.completeKPI
    && state.dashboard?.partialNotice
    && state.dashboard?.points >= 28
    && avif.brand.includes("ftypavif")
    && avif.width === 4
    && avif.height === 4
    && avif.maxChannelDelta === 0;
  process.stdout.write(`${JSON.stringify({ ok, state, avif, workerAsset })}\n`);
  if (!ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
