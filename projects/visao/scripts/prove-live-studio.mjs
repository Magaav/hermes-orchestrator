#!/usr/bin/env node
// Authenticated behavioral proof for one Visão Studio image through a connected Chrome.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const appURL = process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/";
const source = path.resolve(process.argv[2] || "media/visao_before1.jpeg");

function sleep(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

const targetResponse = await fetch(`${cdpOrigin}/json/new?${encodeURIComponent(appURL)}`, { method: "PUT" });
if (!targetResponse.ok) throw new Error(`CDP target creation failed: HTTP ${targetResponse.status}`);
const target = await targetResponse.json();
const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
let requestID = 0;
let studioRequestID = "";
let studioResponseBody = "";
let studioResponse = {};

function command(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++requestID;
    pending.set(id, { resolve, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
}

socket.on("message", (wire) => {
  const message = JSON.parse(String(wire));
  if (message.id && pending.has(message.id)) {
    const current = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) current.reject(new Error(message.error.message || "CDP command failed"));
    else current.resolve(message.result || {});
    return;
  }
  if (message.method === "Network.requestWillBeSent" && String(message.params?.request?.url || "").endsWith("/api/studio/clean")) {
    studioRequestID = message.params.requestId;
  }
  if (message.method === "Network.responseReceived" && message.params?.requestId === studioRequestID) {
    studioResponse = {
      status: message.params.response?.status,
      mimeType: message.params.response?.mimeType,
      protocol: message.params.response?.protocol,
    };
  }
});

await new Promise((resolve, reject) => {
  socket.once("open", resolve);
  socket.once("error", reject);
});

async function evaluate(expression) {
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true,
  });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
  return result.result?.value;
}

async function waitFor(expression, timeoutMilliseconds = 30_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await sleep(250);
  }
  throw new Error(`Browser condition timed out: ${expression.slice(0, 120)}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.enable", { maxTotalBufferSize: 50 * 1024 * 1024, maxResourceBufferSize: 50 * 1024 * 1024 });
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')", 30_000);
  const session = await evaluate(`({
    loginVisible: !![...document.querySelectorAll("button,a")].find((node) => /entrar com google/i.test(node.textContent || "")),
    homeVisible: !![...document.querySelectorAll("button")].find((node) => /^studio/i.test((node.textContent || "").trim()))
  })`);
  if (session.loginVisible || !session.homeVisible) throw new Error("The proof tab is not in an authenticated Visão home.");

  await evaluate(`{
    const button = [...document.querySelectorAll("button")].find((node) => /^studio/i.test((node.textContent || "").trim()));
    button.click();
  }`);
  await waitFor("!!document.querySelector('.studio input[type=file]')");

  const bytes = await fs.readFile(source);
  const base64 = bytes.toString("base64");
  const filename = JSON.stringify(path.basename(source));
  await evaluate(`{
    const bytes = Uint8Array.from(atob(${JSON.stringify(base64)}), (character) => character.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], ${filename}, { type: "image/jpeg" }));
    const input = document.querySelector(".studio input[type=file]");
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }`);
  await waitFor("document.querySelectorAll('.studio-photo').length === 1");
  const sourceImageURL = await evaluate("String(document.querySelector('.studio-photo img')?.src || '')");

  const started = Date.now();
  await evaluate(`{
    const button = [...document.querySelectorAll("button")].find((node) => /tratar fotos/i.test(node.textContent || ""));
    button.click();
  }`);
  const terminal = await waitFor(`(() => {
    const card = document.querySelector(".studio-photo");
    if (!card?.classList.contains("studio-photo--cleaned") && !card?.classList.contains("studio-photo--failed")) return null;
    return {
      state: card.classList.contains("studio-photo--cleaned") ? "cleaned" : "failed",
      label: (card.querySelector(".studio-photo__state")?.textContent || "").trim(),
      error: card.getAttribute("title") || "",
      outputReady: String(card.querySelector("img")?.src || "") !== ${JSON.stringify(sourceImageURL)},
      outputType: card.dataset.outputType || "",
      outputBytes: Number(card.dataset.outputBytes || 0),
      usageComplete: card.dataset.usageComplete === "true",
      elapsedMs: Number(card.dataset.elapsedMs || 0),
      archived: card.dataset.archived === "true",
      sessionId: card.closest(".studio")?.dataset.currentSessionId || ""
    };
  })()`, 240_000);
  await evaluate("document.querySelector('.studio-photo--cleaned')?.click()");
  await waitFor("!!document.querySelector('.studio-modal__dialog')");
  const comparison = await evaluate(`(() => {
    const dialog = document.querySelector(".studio-modal__dialog");
    const image = dialog?.querySelector(".studio-modal__image img");
    const usage = (dialog?.querySelector(".studio-modal__usage")?.textContent || "").replace(/\\s+/g, " ").trim();
    const usageValue = (dialog?.querySelector(".studio-modal__usage-total strong")?.textContent || "").trim();
    return {
      afterURL: String(image?.src || ""),
      usage,
      usageValue,
      usageAvailable: !!usageValue && !/n[aã]o informado/i.test(usageValue),
      usageComplete: /contagem completa/i.test(usage),
      usagePartial: /contagem parcial/i.test(usage)
    };
  })()`);
  await evaluate(`[...document.querySelectorAll(".studio-modal__switch button")].find((button) => /^antes$/i.test((button.textContent || "").trim()))?.click()`);
  const beforeURL = await waitFor(`(() => {
    const image = document.querySelector(".studio-modal__image img");
    return image?.src === ${JSON.stringify(sourceImageURL)} ? image.src : "";
  })()`);
  await evaluate(`[...document.querySelectorAll(".studio-modal__switch button")].find((button) => /^depois$/i.test((button.textContent || "").trim()))?.click()`);
  const afterURL = await waitFor(`(() => {
    const image = document.querySelector(".studio-modal__image img");
    return image?.src && image.src !== ${JSON.stringify(sourceImageURL)} ? image.src : "";
  })()`);
  const output = { type: terminal.outputType, bytes: terminal.outputBytes };
  await evaluate("document.querySelector('[aria-label=\"Fechar comparação\"]')?.click()");
  await evaluate("document.querySelector('[aria-label=\"Dashboard do Studio\"]')?.click()");
  await waitFor("!!document.querySelector('.studio-dashboard') && !document.querySelector('.studio-dashboard__content.is-loading')");
  const dashboard = await evaluate(`(() => ({
    heading: (document.querySelector(".studio-dashboard h1")?.textContent || "").trim(),
    kpis: [...document.querySelectorAll(".studio-kpis article")].map((item) => (item.textContent || "").replace(/\\s+/g, " ").trim()),
    graphReady: !!document.querySelector(".studio-chart__line"),
    pointCount: document.querySelectorAll(".studio-chart__point").length,
    empty: !!document.querySelector(".studio-chart__empty"),
    partialNotice: !!document.querySelector(".studio-dashboard__partial")
  }))()`);
  if (studioRequestID) {
    const response = await command("Network.getResponseBody", { requestId: studioRequestID }).catch(() => ({}));
    studioResponseBody = response.base64Encoded
      ? Buffer.from(response.body || "", "base64").toString("utf8")
      : String(response.body || "");
  }
  const frames = studioResponseBody
    .split("\n")
    .filter((line) => line.trim())
    .map((line) => {
      try {
        const frame = JSON.parse(line);
        return {
          event: String(frame.event || ""),
          code: String(frame.detail?.code || ""),
          proof: frame.detail?.proof || undefined,
        };
      } catch {
        return { event: "invalid-json", code: "" };
      }
    });

  await evaluate("document.querySelector('.studio-dashboard .module-back')?.click()");
  await waitFor("!!document.querySelector('[aria-label=\"Sessões do Studio\"]')");
  await evaluate("document.querySelector('[aria-label=\"Sessões do Studio\"]')?.click()");
  const sessionSelector = `.studio-session-row[data-session-id="${terminal.sessionId}"]`;
  await waitFor(`!!document.querySelector(${JSON.stringify(sessionSelector)}) && !document.querySelector('.studio-sessions__loading')`);
  await evaluate(`document.querySelector(${JSON.stringify(sessionSelector)})?.click()`);
  const archived = await waitFor(`(() => {
    const photo = document.querySelector(".studio-session-photo");
    if (!photo || document.querySelector(".studio-sessions__loading")) return null;
    const page = document.querySelector(".studio-sessions");
    return {
      sessionId: page?.dataset.sessionId || "",
      photos: document.querySelectorAll(".studio-session-photo").length,
      timer: (photo.querySelector(".studio-photo__timer")?.textContent || "").trim(),
      outputUrl: String(photo.querySelector("img")?.src || "")
    };
  })()`);
  const archivedSession = await evaluate(`fetch(${JSON.stringify(`/api/studio/sessions/${terminal.sessionId}`)}, {
    credentials: "same-origin"
  }).then((response) => response.json())`);
  const storedPhoto = archivedSession.photos?.[0] || {};
  const storedFiles = await evaluate(`(async () => {
    const source = await fetch(${JSON.stringify(storedPhoto.sourceUrl || "")}, { credentials: "same-origin" });
    const sourceBytes = (await source.arrayBuffer()).byteLength;
    const output = await fetch(${JSON.stringify(storedPhoto.outputUrl || "")}, { credentials: "same-origin" });
    const outputBytes = (await output.arrayBuffer()).byteLength;
    return {
      source: { status: source.status, type: source.headers.get("content-type"), bytes: sourceBytes },
      output: { status: output.status, type: output.headers.get("content-type"), bytes: outputBytes }
    };
  })()`);

  const ok = terminal.state === "cleaned"
    && terminal.outputReady
    && terminal.archived
    && terminal.elapsedMs > 0
    && terminal.sessionId
    && beforeURL === sourceImageURL
    && afterURL !== sourceImageURL
    && comparison.usageAvailable
    && (comparison.usageComplete || comparison.usagePartial)
    && output.type === "image/avif"
    && output.bytes > 0
    && dashboard.heading === "Dashboard"
    && (dashboard.graphReady || dashboard.partialNotice)
    && archived.sessionId === terminal.sessionId
    && archived.photos === 1
    && archivedSession.photos?.length === 1
    && storedFiles.source.status === 200
    && storedFiles.source.type === "image/jpeg"
    && storedFiles.source.bytes > 0
    && storedFiles.output.status === 200
    && storedFiles.output.type === "image/avif"
    && storedFiles.output.bytes === output.bytes;
  process.stdout.write(`${JSON.stringify({
    ok,
    ...terminal,
    comparison: {
      beforeSwitch: beforeURL === sourceImageURL,
      afterSwitch: afterURL !== sourceImageURL && comparison.afterURL !== sourceImageURL,
      usageAvailable: comparison.usageAvailable,
      usageComplete: comparison.usageComplete,
      usagePartial: comparison.usagePartial,
      usageValue: comparison.usageValue,
      usage: comparison.usage,
    },
    output,
    dashboard,
    archived,
    storedFiles,
    response: studioResponse,
    frames,
    elapsedMs: Date.now() - started,
  })}\n`);
  if (!ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
