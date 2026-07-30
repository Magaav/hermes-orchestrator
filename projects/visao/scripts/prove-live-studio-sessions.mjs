#!/usr/bin/env node
// Authenticated, non-billable proof for per-photo timer and Studio session lifecycle.

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
  const result = await command("Runtime.evaluate", {
    expression,
    awaitPromise: true,
    returnByValue: true
  });
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
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Page.navigate", { url: `${appURL}?studio-session-proof=${Date.now()}` });
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')");
  await evaluate(`[...document.querySelectorAll("button")]
    .find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  await waitFor("!!document.querySelector('.studio input[type=file]')");

  const bytes = await fs.readFile(source);
  const base64 = bytes.toString("base64");
  await evaluate(`{
    const bytes = Uint8Array.from(atob(${JSON.stringify(base64)}), (character) => character.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], ${JSON.stringify(path.basename(source))}, { type: "image/jpeg" }));
    const input = document.querySelector(".studio input[type=file]");
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }`);
  const timer = await waitFor(`(() => {
    const card = document.querySelector(".studio-photo");
    const value = (card?.querySelector(".studio-photo__timer")?.textContent || "").trim();
    return card && value ? { value, elapsedMs: Number(card.dataset.elapsedMs || -1) } : null;
  })()`);

  await evaluate("document.querySelector('[aria-label=\"Sessões do Studio\"]')?.click()");
  await waitFor("!!document.querySelector('.studio-sessions') && !document.querySelector('.studio-sessions__loading')");
  const initial = await evaluate(`fetch("/api/studio/sessions", { credentials: "same-origin" })
    .then((response) => response.json())`);
  const existingSessionURL = initial.items?.[0] ? `/api/studio/sessions/${initial.items[0].id}` : "";
  const existingFiles = initial.items?.[0] ? await evaluate(`(async () => {
    try {
      const detailResponse = await fetch(${JSON.stringify(existingSessionURL)}, { credentials: "same-origin" });
      const detail = await detailResponse.json();
      const photo = detail.photos?.[0];
      if (!photo) return { skipped: true };
      const source = await fetch(photo.sourceUrl, { credentials: "same-origin" });
      const sourceBytes = (await source.arrayBuffer()).byteLength;
      const output = await fetch(photo.outputUrl, { credentials: "same-origin" });
      const outputBytes = (await output.arrayBuffer()).byteLength;
      return {
        sessionId: detail.id,
        photoId: photo.id,
        source: { status: source.status, type: source.headers.get("content-type"), bytes: sourceBytes },
        output: { status: output.status, type: output.headers.get("content-type"), bytes: outputBytes },
        elapsedMs: photo.elapsedMs
      };
    } catch (error) {
      return { error: String(error), stack: String(error?.stack || "") };
    }
  })()`) : { skipped: true };
  const created = await evaluate(`fetch("/api/studio/sessions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  }).then((response) => response.json())`);
  if (!created?.id) throw new Error("Session creation did not return an id.");

  await evaluate("document.querySelector('.studio-sessions .module-back')?.click()");
  await waitFor("!!document.querySelector('[aria-label=\"Sessões do Studio\"]')");
  await evaluate("document.querySelector('[aria-label=\"Sessões do Studio\"]')?.click()");
  const selector = `.studio-session-row[data-session-id="${created.id}"]`;
  await waitFor(`!!document.querySelector(${JSON.stringify(selector)})`);
  await evaluate(`document.querySelector(${JSON.stringify(selector)})?.click()`);
  const opened = await waitFor(`(() => {
    const page = document.querySelector('.studio-sessions[data-session-id="${created.id}"]');
    if (!page || document.querySelector(".studio-sessions__loading")) return null;
    return {
      empty: !!page.querySelector(".studio-sessions__empty"),
      navigation: (page.querySelector(".studio-session__navigation")?.textContent || "").trim(),
      canDelete: !![...page.querySelectorAll("button")].find((button) => /excluir/i.test(button.textContent || ""))
    };
  })()`);

  await evaluate(`window.confirm = () => true`);
  await evaluate(`[...document.querySelectorAll(".studio-session__actions button")]
    .find((button) => /excluir/i.test(button.textContent || ""))?.click()`);
  await waitFor(`!document.querySelector(${JSON.stringify(selector)}) && !!document.querySelector(".studio-session-list, .studio-sessions__empty")`);
  const removed = await evaluate(`Promise.all([
    fetch("/api/studio/sessions/${created.id}", { credentials: "same-origin" }).then((response) => response.status),
    fetch("/api/studio/sessions", { credentials: "same-origin" }).then((response) => response.json())
  ]).then(([status, list]) => ({
    status,
    remains: list.items.some((item) => item.id === ${JSON.stringify(created.id)}),
    count: list.count
  }))`);

  const ok = timer.value.includes("00:00")
    && timer.elapsedMs === 0
    && created.photoCount === 0
    && opened.empty
    && opened.canDelete
    && removed.status === 404
    && !removed.remains
    && removed.count === initial.count
    && (existingFiles.skipped || (
      existingFiles.source?.status === 200
      && existingFiles.source?.type === "image/jpeg"
      && existingFiles.source?.bytes > 0
      && existingFiles.output?.status === 200
      && existingFiles.output?.type === "image/avif"
      && existingFiles.output?.bytes > 0
      && existingFiles.elapsedMs > 0
    ));
  process.stdout.write(`${JSON.stringify({ ok, timer, initialCount: initial.count, existingFiles, createdId: created.id, opened, removed })}\n`);
  if (!ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
