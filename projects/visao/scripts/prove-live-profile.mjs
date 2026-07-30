#!/usr/bin/env node
// Authenticated browser proof for the topbar profile modal.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import path from "node:path";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdpOrigin = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const appURL = new URL(process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/");
const screenshotPath = path.resolve(process.argv[2] || "/tmp/visao-profile-modal.png");
appURL.searchParams.set("profile-proof", String(Date.now()));

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
  const current = pending.get(message.id);
  if (!current) return;
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

async function waitFor(expression, timeoutMilliseconds = 45_000) {
  const deadline = Date.now() + timeoutMilliseconds;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await sleep(150);
  }
  throw new Error(`Browser condition timed out: ${expression.slice(0, 140)}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Emulation.setDeviceMetricsOverride", { width: 1280, height: 850, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: String(appURL) });
  await waitFor("document.readyState === 'complete' && !!document.querySelector('.topbar__profile-trigger')");

  const topbar = await evaluate(`(() => {
    const bar = document.querySelector(".topbar").getBoundingClientRect();
    const user = document.querySelector(".topbar__user").getBoundingClientRect();
    const style = getComputedStyle(document.querySelector(".topbar"));
    return {
      visibleLogout: [...document.querySelectorAll(".topbar button")].some((node) =>
        !node.closest(".profile-modal") && (node.textContent || "").trim() === "Sair"),
      triggerName: (document.querySelector(".topbar__profile-trigger strong")?.textContent || "").trim(),
      triggerEmail: (document.querySelector(".topbar__profile-trigger small")?.textContent || "").trim(),
      padding: [style.paddingTop, style.paddingRight, style.paddingBottom, style.paddingLeft],
      userMargins: {
        top: Math.round((user.top - bar.top) * 10) / 10,
        right: Math.round((bar.right - user.right) * 10) / 10,
        bottom: Math.round((bar.bottom - user.bottom) * 10) / 10
      }
    };
  })()`);

  await evaluate("document.querySelector('.topbar__profile-trigger')?.click()");
  const modal = await waitFor(`(() => {
    const dialog = document.querySelector(".profile-modal__dialog");
    if (!dialog) return null;
    return {
      name: (dialog.querySelector("h2")?.textContent || "").trim(),
      email: (dialog.querySelector(".profile-modal__identity p")?.textContent || "").trim(),
      roles: [...dialog.querySelectorAll(".profile-modal__roles b")].map((node) => (node.textContent || "").trim()),
      logout: (dialog.querySelector(".profile-modal__logout")?.textContent || "").trim(),
      photoChange: dialog.querySelector('input[type="file"]')?.getAttribute("accept") || ""
    };
  })()`);

  const capture = await command("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
  await fs.writeFile(screenshotPath, Buffer.from(capture.data, "base64"));

  const result = {
    ok: !topbar.visibleLogout
      && topbar.triggerName === modal.name
      && topbar.triggerEmail === modal.email
      && modal.roles.length > 0
      && modal.logout === "Sair"
      && modal.photoChange === "image/jpeg,image/png,image/webp"
      && topbar.padding.every((value) => value === "10px")
      && topbar.userMargins.right === 10
      && topbar.userMargins.top === topbar.userMargins.bottom,
    topbar,
    modal,
    screenshotPath
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (!result.ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdpOrigin}/json/close/${target.id}`).catch(() => undefined);
}
