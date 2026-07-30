#!/usr/bin/env node
// Authenticated proof for Atendimento PDF modal and all-documents ZIP.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdp = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const url = new URL(process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/");
const atendimento = process.env.VISAO_PROOF_ATENDIMENTO || "123456";
const screenshotPath = process.argv[2] || "/tmp/visao-atendimento-document-modal.png";
url.searchParams.set("documents-proof", String(Date.now()));

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
  const result = await command("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || "Browser evaluation failed");
  return result.result?.value;
}

async function waitFor(expression, timeout = 45_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`Timed out: ${expression}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Emulation.setDeviceMetricsOverride", { width: 1440, height: 1000, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: String(url) });
  await waitFor("document.documentElement.classList.contains('app-ready') && !!document.querySelector('.home')");

  const submission = await evaluate(`fetch("/api/submissions", { credentials: "same-origin" })
    .then((response) => response.json())
    .then((body) => body.items.find((item) => item.atendimento === ${JSON.stringify(atendimento)}))`);
  if (!submission?.id) throw new Error(`Atendimento ${atendimento} was not found`);

  await evaluate(`[...document.querySelectorAll(".module-card")].find((node) => /atendimento/i.test(node.textContent || ""))?.click()`);
  await waitFor("document.querySelectorAll('.record-row').length");
  await evaluate(`[...document.querySelectorAll(".record-row")]
    .find((node) => (node.querySelector(".record-row__main strong")?.textContent || "").trim() === ${JSON.stringify(atendimento)})?.click()`);
  await waitFor("!!document.querySelector('.workspace')");
  await evaluate(`[...document.querySelectorAll(".workspace-nav nav button")]
    .find((node) => /documentos/i.test(node.textContent || ""))?.click()`);
  const attached = await waitFor("document.querySelectorAll('.attached-files__open').length");
  const downloadButton = await evaluate(`(() => {
    const button = document.querySelector(".workspace-header__documents");
    return { text: (button?.textContent || "").trim(), disabled: button?.disabled };
  })()`);

  await evaluate("document.querySelector('.attached-files__open')?.click()");
  const modal = await waitFor(`(() => {
    const dialog = document.querySelector(".document-modal__dialog");
    const frame = dialog?.querySelector("iframe");
    const download = dialog?.querySelector("a[download]");
    return dialog && frame ? {
      title: (dialog.querySelector("h2")?.textContent || "").trim(),
      frame: frame.getAttribute("src"),
      download: download?.getAttribute("href") || ""
    } : null;
  })()`);
  const pdf = await evaluate(`fetch(${JSON.stringify(modal.frame)}, { credentials: "same-origin" }).then(async (response) => ({
    status: response.status,
    type: response.headers.get("content-type"),
    frame: response.headers.get("x-frame-options"),
    policy: response.headers.get("content-security-policy"),
    bytes: (await response.arrayBuffer()).byteLength
  }))`);
  const capture = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await fs.writeFile(screenshotPath, Buffer.from(capture.data, "base64"));

  const archive = await evaluate(`fetch(${JSON.stringify(`/api/submissions/${submission.id}/documents`)}, { credentials: "same-origin" }).then(async (response) => {
    const bytes = new Uint8Array(await response.arrayBuffer());
    return {
      status: response.status,
      type: response.headers.get("content-type"),
      disposition: response.headers.get("content-disposition"),
      bytes: bytes.length,
      signature: [...bytes.slice(0, 4)]
    };
  })`);

  const result = {
    ok: attached >= 1
      && !downloadButton.disabled
      && /baixar documentos/i.test(downloadButton.text)
      && modal.download.endsWith("download=1")
      && pdf.status === 200
      && pdf.type === "application/pdf"
      && pdf.frame === "SAMEORIGIN"
      && pdf.policy === "frame-ancestors 'self'"
      && pdf.bytes > 5
      && archive.status === 200
      && archive.type === "application/zip"
      && /attachment;/.test(archive.disposition)
      && archive.bytes > pdf.bytes
      && JSON.stringify(archive.signature) === JSON.stringify([80, 75, 3, 4]),
    atendimento,
    submissionID: submission.id,
    attached,
    downloadButton,
    modal,
    pdf,
    archive,
    screenshotPath
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (!result.ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdp}/json/close/${target.id}`).catch(() => undefined);
}
