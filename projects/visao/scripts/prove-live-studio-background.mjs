#!/usr/bin/env node
// Authenticated, non-billable proof that Studio survives in-app navigation while processing.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const appURL = process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/";
const source = path.resolve(process.argv[2] || "media/visao_before1.jpeg");
const screenshotPath = path.resolve(process.env.VISAO_PROOF_SCREENSHOT || "/tmp/visao-studio-timer-proof.png");
const viewportWidth = Number(process.env.VISAO_PROOF_VIEWPORT_WIDTH || 1280);
const viewportHeight = Number(process.env.VISAO_PROOF_VIEWPORT_HEIGHT || 900);
const bytes = await fs.readFile(source);
const imageBase64 = bytes.toString("base64");
const imageChunks = imageBase64.match(/.{1,8192}/g) || [];
const sessionID = "111111111111111111111111";
const photoID = "222222222222222222222222";
const traceID = "background_navigation_proof";

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

async function waitFor(expression, timeoutMilliseconds = 60_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await sleep(150);
  }
  throw new Error(`Browser condition timed out: ${expression.slice(0, 120)}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Emulation.setDeviceMetricsOverride", {
    width: viewportWidth,
    height: viewportHeight,
    deviceScaleFactor: 1,
    mobile: false
  });
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Page.navigate", { url: `${appURL}?studio-background-proof=${Date.now()}` });
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')");

  await evaluate(`(() => {
    const originalFetch = window.fetch.bind(window);
    const encoder = new TextEncoder();
    const json = (value, status = 200) => new Response(JSON.stringify(value), {
      status,
      headers: { "Content-Type": "application/json" }
    });
    let session = null;
    let photo = null;
    window.fetch = async (input, init = {}) => {
      const requestURL = new URL(typeof input === "string" ? input : input.url, location.href);
      const method = String(init.method || (typeof input === "string" ? "GET" : input.method) || "GET").toUpperCase();
      if (requestURL.pathname === "/api/studio/clean" && method === "POST") {
        const metadata = {
          ok: true,
          media_type: "image/jpeg",
          proof: {
            trace_id: ${JSON.stringify(traceID)},
            provider_model: "gpt-5.5",
            usage: {
              available: true,
              complete: false,
              main_available: true,
              image_available: false,
              main_input_tokens: 10,
              cached_main_input_tokens: 0,
              main_output_tokens: 2,
              reasoning_output_tokens: 0,
              image_input_tokens: 0,
              image_output_tokens: 0,
              image_text_input_tokens: 0,
              image_source_input_tokens: 0,
              total_tokens: 12
            }
          }
        };
        const chunks = ${JSON.stringify(imageChunks)};
        const stream = new ReadableStream({
          start(controller) {
            controller.enqueue(encoder.encode(JSON.stringify({ event: "accepted", detail: {} }) + "\\n"));
            setTimeout(() => {
              controller.enqueue(encoder.encode(JSON.stringify({ event: "result-start", detail: { result: metadata, chunks: chunks.length } }) + "\\n"));
              chunks.forEach((chunk, index) => controller.enqueue(encoder.encode(JSON.stringify({ event: "result-chunk", detail: { index, data: chunk } }) + "\\n")));
              controller.enqueue(encoder.encode(JSON.stringify({ event: "complete", detail: { chunks: chunks.length } }) + "\\n"));
              controller.close();
            }, 1400);
          }
        });
        return new Response(stream, {
          status: 200,
          headers: { "Content-Type": "application/x-ndjson; charset=utf-8" }
        });
      }
      if (requestURL.pathname === "/api/studio/sessions" && method === "POST") {
        const now = new Date().toISOString();
        session = { id: ${JSON.stringify(sessionID)}, createdAt: now, updatedAt: now, photoCount: 0, totalElapsedMs: 0, totalBytes: 0, photos: [] };
        return json(session, 201);
      }
      if (requestURL.pathname === "/api/studio/sessions" && method === "GET") {
        return json({ items: session ? [session] : [], count: session ? 1 : 0 });
      }
      if (requestURL.pathname === "/api/studio/sessions/${sessionID}/photos" && method === "POST") {
        const form = init.body;
        const sourceFile = form.get("source");
        const outputFile = form.get("output");
        const elapsedMs = Number(form.get("elapsedMs") || 0);
        photo = {
          id: ${JSON.stringify(photoID)},
          sourceName: sourceFile.name,
          sourceType: sourceFile.type,
          outputType: outputFile.type,
          sourceBytes: sourceFile.size,
          outputBytes: outputFile.size,
          elapsedMs,
          createdAt: new Date().toISOString(),
          sourceUrl: URL.createObjectURL(sourceFile),
          outputUrl: URL.createObjectURL(outputFile),
          proof: { trace_id: ${JSON.stringify(traceID)}, provider_model: "gpt-5.5", usage: { available: true, complete: false, total_tokens: 12 } }
        };
        session = { ...session, updatedAt: new Date().toISOString(), photoCount: 1, totalElapsedMs: elapsedMs, totalBytes: outputFile.size, photos: [photo] };
        return json(photo, 201);
      }
      if (requestURL.pathname === "/api/studio/sessions/${sessionID}" && method === "GET") {
        return session ? json(session) : json({ message: "not found" }, 404);
      }
      return originalFetch(input, init);
    };
  })()`);

  await evaluate(`[...document.querySelectorAll("button")]
    .find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  await waitFor("!!document.querySelector('.studio input[type=file]')");
  await evaluate(`{
    const bytes = Uint8Array.from(atob(${JSON.stringify(imageBase64)}), (character) => character.charCodeAt(0));
    const transfer = new DataTransfer();
    transfer.items.add(new File([bytes], ${JSON.stringify(path.basename(source))}, { type: "image/jpeg" }));
    const input = document.querySelector(".studio input[type=file]");
    input.files = transfer.files;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }`);
  await waitFor("!!document.querySelector('.studio-photo')");
  await evaluate(`[...document.querySelectorAll(".studio-bar button")]
    .find((node) => /tratar fotos/i.test(node.textContent || ""))?.click()`);
  await waitFor("document.querySelector('.studio-photo')?.classList.contains('studio-photo--cleaning')");
  await evaluate("document.querySelector('.studio .module-back')?.click()");
  const whileHidden = await waitFor(`(() => {
    const homeStudio = [...document.querySelectorAll("button")].find((node) => /^studio/i.test((node.textContent || "").trim()));
    const hiddenCard = document.querySelector("[hidden] .studio-photo");
    return homeStudio && hiddenCard ? {
      homeVisible: true,
      cardPreserved: true,
      state: hiddenCard.className,
      timer: (hiddenCard.querySelector(".studio-photo__timer")?.textContent || "").trim()
    } : null;
  })()`);
  await evaluate(`[...document.querySelectorAll("button")]
    .find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  const restored = await waitFor(`(() => {
    const card = document.querySelector(".studio:not([hidden]) .studio-photo, [data-current-session-id] .studio-photo");
    if (!card?.classList.contains("studio-photo--cleaned")) return null;
    return {
      cards: document.querySelectorAll(".studio-photo").length,
      archived: card.dataset.archived === "true",
      elapsedMs: Number(card.dataset.elapsedMs || 0),
      outputType: card.dataset.outputType || ""
    };
  })()`, 60_000);
  await evaluate("document.querySelector('[aria-label=\"Sessões do Studio\"]')?.click()");
  await waitFor(`!!document.querySelector('.studio-session-row[data-session-id="${sessionID}"]')`);
  await evaluate(`document.querySelector('.studio-session-row[data-session-id="${sessionID}"]')?.click()`);
  const history = await waitFor(`(() => {
    const page = document.querySelector('.studio-sessions[data-session-id="${sessionID}"]');
    const photo = page?.querySelector(".studio-session-photo");
    const timer = photo?.querySelector(".studio-photo__timer");
    const icon = timer?.querySelector("svg");
    const value = timer?.querySelector(".studio-photo__timer-value");
    const pillRect = timer?.getBoundingClientRect();
    const iconRect = icon?.getBoundingClientRect();
    const valueRect = value?.getBoundingClientRect();
    const round = (number) => Math.round(number * 100) / 100;
    return photo ? {
      sessionId: page.dataset.sessionId,
      photos: page.querySelectorAll(".studio-session-photo").length,
      timer: (timer?.textContent || "").trim(),
      timerLayout: pillRect && iconRect && valueRect ? {
        width: round(pillRect.width),
        height: round(pillRect.height),
        iconCenterYOffset: round((iconRect.top + iconRect.height / 2) - (pillRect.top + pillRect.height / 2)),
        valueCenterYOffset: round((valueRect.top + valueRect.height / 2) - (pillRect.top + pillRect.height / 2)),
        valueCenterXOffset: round(
          (valueRect.left + valueRect.width / 2) - (pillRect.left + pillRect.width / 2)
        )
      } : null
    } : null;
  })()`);
  const screenshot = await command("Page.captureScreenshot", { format: "png" });
  await fs.writeFile(screenshotPath, Buffer.from(screenshot.data, "base64"));

  const ok = whileHidden.homeVisible
    && whileHidden.cardPreserved
    && restored.cards === 1
    && restored.archived
    && restored.elapsedMs > 0
    && restored.outputType === "image/avif"
    && history.sessionId === sessionID
    && history.photos === 1
    && history.timerLayout?.height === 28
    && Math.abs(history.timerLayout.iconCenterYOffset) <= 1
    && Math.abs(history.timerLayout.valueCenterYOffset) <= 1
    && Math.abs(history.timerLayout.valueCenterXOffset) <= 1;
  process.stdout.write(`${JSON.stringify({ ok, whileHidden, restored, history, screenshotPath })}\n`);
  if (!ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
