#!/usr/bin/env node
"use strict";

const http = require("http");
const WebSocket = require("ws");

const endpoint = String(process.argv[2] || "http://127.0.0.1:9222").replace(/\/$/, "");
const timeoutMs = 12_000;

function getJson(url) {
  return new Promise((resolve, reject) => {
    const request = http.get(url, { timeout: 3_000 }, (response) => {
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

async function inject() {
  const version = await getJson(`${endpoint}/json/version`);
  const targets = await getJson(`${endpoint}/json/list`);
  const page = targets.find((target) => {
    if (target.type !== "page") return false;
    try { return new URL(String(target.url || "")).hostname === "wa.colmeio.com"; } catch { return false; }
  });
  if (!page) throw new Error("production_page_not_found");

  return new Promise((resolve, reject) => {
    const socket = new WebSocket(page.webSocketDebuggerUrl, { handshakeTimeout: 3_000 });
    const timer = setTimeout(() => {
      socket.terminate();
      reject(new Error("stall_fixture_timeout"));
    }, timeoutMs);
    socket.on("open", () => {
      const expression = `(async () => {
        const originalFetch = window.fetch;
        let injected = false;
        window.fetch = async function(input, init = {}) {
          const url = typeof input === "string" ? input : String(input?.url || "");
          if (!injected && url.includes("/agent/provider/envelope/stream")) {
            injected = true;
            window.fetch = originalFetch;
            const requestBody = JSON.parse(String(init.body || "{}"));
            return originalFetch.call(this, input, {
              ...init,
              body: JSON.stringify({ ...requestBody, debug_fixture: "v6_no_semantic_progress" }),
            });
          }
          return originalFetch.call(this, input, init);
        };
        const input = document.querySelector("#agentInput");
        const send = document.querySelector("#agentSendButton");
        if (!input || !send || input.disabled || send.disabled) {
          window.fetch = originalFetch;
          throw new Error("agent_controls_unavailable");
        }
        input.value = "Controlled persisted stall proof: report the unresolved requirement.";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        send.click();
        const deadline = Date.now() + 9000;
        while (Date.now() < deadline) {
          await new Promise((done) => setTimeout(done, 200));
          const text = String(document.querySelector("#agentMessages")?.innerText || "");
          if (text.includes("Unresolved requirements: completion:repo.read")) {
            return {
              ok: true,
              injected,
              fetch_restored: window.fetch === originalFetch,
              pending: document.querySelectorAll('[data-agent-run-status="running"],.is-pending,[aria-busy="true"]').length,
              answer: text.slice(-500),
              href: location.href,
            };
          }
        }
        window.fetch = originalFetch;
        return { ok: false, injected, fetch_restored: true, reason: "fallback_not_visible", href: location.href };
      })()`;
      socket.send(JSON.stringify({
        id: 1,
        method: "Runtime.evaluate",
        params: { expression, awaitPromise: true, returnByValue: true },
      }));
    });
    socket.on("message", (raw) => {
      const message = JSON.parse(String(raw));
      if (message.id !== 1) return;
      clearTimeout(timer);
      socket.close();
      const exception = message.result?.exceptionDetails;
      if (exception) return reject(new Error(exception.exception?.description || exception.text || "cdp_evaluate_failed"));
      resolve({
        schema: "hermes.wasm_agent.master_frontier.stall_fixture.v1",
        browser: version.Browser || "",
        protocol: version["Protocol-Version"] || "",
        ...message.result?.result?.value,
      });
    });
    socket.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}

inject()
  .then((result) => {
    process.stdout.write(`${JSON.stringify(result)}\n`);
    if (result.ok !== true) process.exitCode = 2;
  })
  .catch((error) => {
    process.stdout.write(`${JSON.stringify({ ok: false, error: String(error.message || error) })}\n`);
    process.exitCode = 2;
  });
