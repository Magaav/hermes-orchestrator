#!/usr/bin/env node
// Browser proof for the pre-paint Visão launcher and automatic app reveal.

import fs from "node:fs/promises";
import { createRequire } from "node:module";
import process from "node:process";

const require = createRequire(new URL("../frontend/package.json", import.meta.url));
const WebSocket = require("ws");
const cdp = process.env.VISAO_CDP_ORIGIN || "http://127.0.0.1:9222";
const url = new URL(process.env.VISAO_PROOF_URL || "https://visao.colmeio.com/");
url.searchParams.set("launcher-proof", String(Date.now()));
const screenshotPath = process.argv[2] || "/tmp/visao-launcher.png";

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

async function waitFor(expression, timeout = 45_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) {
    const value = await evaluate(expression);
    if (value) return value;
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`Timed out: ${expression}`);
}

try {
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Network.setBypassServiceWorker", { bypass: true });
  await command("Emulation.setDeviceMetricsOverride", { width: 1280, height: 850, deviceScaleFactor: 1, mobile: false });
  await command("Page.navigate", { url: String(url) });
  await waitFor("!!document.querySelector('#app-launcher .launcher-eye')");
  await new Promise((resolve) => setTimeout(resolve, 500));

  const launcher = await evaluate(`(() => {
    const node = document.querySelector("#app-launcher");
    const style = getComputedStyle(node);
    const ripple = getComputedStyle(node.querySelector(".launcher-ripple"));
    const eye = getComputedStyle(node.querySelector(".launcher-eye"));
    return {
      visible: style.visibility === "visible" && Number(style.opacity) > 0,
      ripples: node.querySelectorAll(".launcher-ripple").length,
      eye: !!node.querySelector(".launcher-eye svg"),
      label: node.getAttribute("aria-label"),
      reducedMotion: matchMedia("(prefers-reduced-motion: reduce)").matches,
      animation: {
        ripple: [ripple.animationName, ripple.animationDuration, ripple.animationPlayState],
        eye: [eye.animationName, eye.animationDuration, eye.animationPlayState]
      },
      sample: {
        ripple: ripple.transform,
        eye: eye.transform
      }
    };
  })()`);
  await new Promise((resolve) => setTimeout(resolve, 220));
  launcher.nextSample = await evaluate(`(() => ({
    ripple: getComputedStyle(document.querySelector(".launcher-ripple")).transform,
    eye: getComputedStyle(document.querySelector(".launcher-eye")).transform
  }))()`);
  launcher.motionChanged = launcher.sample.ripple !== launcher.nextSample.ripple || launcher.sample.eye !== launcher.nextSample.eye;
  const capture = await command("Page.captureScreenshot", { format: "png" });
  await fs.writeFile(screenshotPath, Buffer.from(capture.data, "base64"));

  const revealed = await waitFor(`(() => {
    const launcher = document.querySelector("#app-launcher");
    return document.documentElement.classList.contains("app-ready")
      && getComputedStyle(launcher).visibility === "hidden"
      && !!document.querySelector(".home");
  })()`);
  const result = {
    ok: launcher.visible && launcher.ripples === 3 && launcher.eye && launcher.label === "Carregando Visão Imóveis" && launcher.motionChanged && revealed,
    launcher,
    revealed,
    screenshotPath
  };
  process.stdout.write(`${JSON.stringify(result)}\n`);
  if (!result.ok) process.exitCode = 1;
} finally {
  socket.close();
  await fetch(`${cdp}/json/close/${target.id}`).catch(() => undefined);
}
