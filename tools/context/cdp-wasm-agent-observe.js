#!/usr/bin/env node
"use strict";

const http = require("http");
const WebSocket = require("ws");

function getJson(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: 3000 }, (response) => {
      let body = "";
      response.setEncoding("utf8");
      response.on("data", (chunk) => { body += chunk; });
      response.on("end", () => {
        try { resolve(JSON.parse(body)); } catch (error) { reject(error); }
      });
    });
    request.on("timeout", () => request.destroy(new Error("cdp_timeout")));
    request.on("error", reject);
  });
}

async function observe(endpoint, sessionId, runId) {
  const version = await getJson(`${endpoint}/json/version`);
  const targets = await getJson(`${endpoint}/json/list`);
  const page = targets.find((target) => (
    target.type === "page"
    && String(target.url || "").startsWith("https://wa.colmeio.com/home")
  ));
  if (!page) {
    return { available: true, browser: version.Browser || "", page: null };
  }
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(page.webSocketDebuggerUrl, { handshakeTimeout: 3000 });
    const timer = setTimeout(() => {
      socket.terminate();
      reject(new Error("cdp_evaluate_timeout"));
    }, 4000);
    socket.on("open", () => {
      const expression = `(() => {
        const sessionId = ${JSON.stringify(sessionId)};
        const runId = ${JSON.stringify(process.argv[4] || "")};
        const sessions = Array.isArray(window.__wasmAgentArchitectureMetrics?.sessions)
          ? window.__wasmAgentArchitectureMetrics.sessions : null;
        const text = String(document.body?.innerText || "");
        const savedRuns = [...text.matchAll(/Saved run:\\s*([A-Za-z0-9_.:-]+)/g)].map((match) => match[1]);
        const savedRun = savedRuns.at(-1) || "";
        const interrupted = Boolean(runId && savedRun === runId);
        const pending = [...document.querySelectorAll('[data-agent-run-status="running"], .is-pending, [aria-busy="true"]')].length;
        return {
          visibility: document.visibilityState,
          href: location.href,
          session_id: sessionId,
          interrupted_visible: interrupted,
          saved_run_id: savedRun,
          pending_markers: pending,
          sessions_metric_available: sessions !== null
        };
      })()`;
      socket.send(JSON.stringify({
        id: 1,
        method: "Runtime.evaluate",
        params: { expression, returnByValue: true },
      }));
    });
    socket.on("message", (raw) => {
      const message = JSON.parse(String(raw));
      if (message.id !== 1) return;
      clearTimeout(timer);
      socket.close();
      resolve({
        available: true,
        browser: version.Browser || "",
        protocol: version["Protocol-Version"] || "",
        page: message.result?.result?.value || null,
      });
    });
    socket.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

const endpoint = String(process.argv[2] || "http://127.0.0.1:9222").replace(/\/$/, "");
const sessionId = String(process.argv[3] || "");
const runId = String(process.argv[4] || "");
observe(endpoint, sessionId, runId)
  .then((result) => process.stdout.write(`${JSON.stringify(result)}\n`))
  .catch((error) => {
    process.stdout.write(`${JSON.stringify({ available: false, error: String(error.message || error) })}\n`);
    process.exitCode = 2;
  });
