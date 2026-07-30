#!/usr/bin/env node
// Authenticated, read-only browser proof for Studio dashboard controls.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const appURL = process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/";
const screenshot = path.resolve(process.argv[2] || "/tmp/visao-studio-dashboard-full.png");

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

async function selectPeriod(label) {
  await evaluate(`{
    const button = [...document.querySelectorAll(".studio-dashboard__toolbar .studio-segmented button")]
      .find((node) => (node.textContent || "").trim() === ${JSON.stringify(label)});
    button?.click();
  }`);
  return waitFor(`(() => {
    const active = document.querySelector(".studio-dashboard__toolbar .studio-segmented button.is-active");
    if ((active?.textContent || "").trim() !== ${JSON.stringify(label)} || document.querySelector(".studio-dashboard__content.is-loading")) return null;
    return document.querySelectorAll(".studio-chart__point").length;
  })()`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')");
  await evaluate(`[...document.querySelectorAll("button")].find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  await waitFor("!!document.querySelector('[aria-label=\"Dashboard do Studio\"]')");
  await evaluate("document.querySelector('[aria-label=\"Dashboard do Studio\"]')?.click()");
  await waitFor("!!document.querySelector('.studio-dashboard') && !document.querySelector('.studio-dashboard__content.is-loading')");

  await evaluate(`[...document.querySelectorAll(".studio-dashboard__heading .studio-segmented button")]
    .find((node) => /todos/i.test(node.textContent || ""))?.click()`);
  const everybody = await waitFor(`(() => {
    const active = document.querySelector(".studio-dashboard__heading .studio-segmented button.is-active");
    if (!/todos/i.test(active?.textContent || "") || document.querySelector(".studio-dashboard__content.is-loading")) return null;
    const kpis = document.querySelectorAll(".studio-kpis article");
    const readNumber = (node) => Number((node?.textContent || "").replace(/\\D/g, "")) || 0;
    return {
      userRows: document.querySelectorAll(".studio-user-row").length,
      averageTokens: readNumber(kpis[0]?.querySelector("strong")),
      totalTokens: readNumber(kpis[1]?.querySelector("strong")),
      reportedPictures: readNumber(kpis[2]?.querySelector("strong"))
    };
  })()`);

  const dayPoints = await selectPeriod("Dia");
  const monthPoints = await selectPeriod("Mês");
  const yearPoints = await selectPeriod("Ano");
  const beforeNavigation = await evaluate("(document.querySelector('.studio-period-nav strong')?.textContent || '').trim()");
  await evaluate("document.querySelector('.studio-period-nav button')?.click()");
  const afterNavigation = await waitFor(`(() => {
    if (document.querySelector(".studio-dashboard__content.is-loading")) return "";
    const label = (document.querySelector(".studio-period-nav strong")?.textContent || "").trim();
    return label && label !== ${JSON.stringify(beforeNavigation)} ? label : "";
  })()`);
  await evaluate("location.reload()");
  await waitFor("document.readyState === 'complete' && !!document.querySelector('main')");
  await evaluate(`[...document.querySelectorAll("button")].find((node) => /^studio/i.test((node.textContent || "").trim()))?.click()`);
  await waitFor("!!document.querySelector('[aria-label=\"Dashboard do Studio\"]')");
  await evaluate("document.querySelector('[aria-label=\"Dashboard do Studio\"]')?.click()");
  await waitFor("!!document.querySelector('.studio-dashboard') && !document.querySelector('.studio-dashboard__content.is-loading')");
  await evaluate(`[...document.querySelectorAll(".studio-dashboard__heading .studio-segmented button")]
    .find((node) => /todos/i.test(node.textContent || ""))?.click()`);
  await waitFor(`(() => {
    const active = document.querySelector(".studio-dashboard__heading .studio-segmented button.is-active");
    return /todos/i.test(active?.textContent || "") && !document.querySelector(".studio-dashboard__content.is-loading");
  })()`);

  const capture = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await fs.writeFile(screenshot, Buffer.from(capture.data, "base64"));
  const result = {
    ok: dayPoints === 24
      && monthPoints >= 28
      && monthPoints <= 31
      && yearPoints === 12
      && everybody.userRows > 0
      && everybody.averageTokens > 0
      && everybody.totalTokens > 0
      && everybody.reportedPictures > 0
      && Boolean(afterNavigation),
    everybody,
    points: { day: dayPoints, month: monthPoints, year: yearPoints },
    navigation: { before: beforeNavigation, after: afterNavigation },
    screenshot,
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (!result.ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
