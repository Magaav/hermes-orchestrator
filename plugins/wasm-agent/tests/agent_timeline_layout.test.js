#!/usr/bin/env node
const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { chromium } = require("../../../tools/app-simulator/node_modules/playwright-core");

function chromiumExecutablePath() {
  for (const candidate of [
    process.env.CHROMIUM,
    process.env.WASM_AGENT_SIM_CHROMIUM,
    "/snap/bin/chromium",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
  ]) {
    if (candidate && fs.existsSync(candidate)) return candidate;
  }
  return undefined;
}

(async () => {
  const root = path.resolve(__dirname, "..");
  const css = fs.readFileSync(path.join(root, "public", "styles.css"), "utf8");
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromiumExecutablePath(),
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage({ viewport: { width: 360, height: 760 }, isMobile: true });
    const long = "wasm-agent.avatar-chat.ui/route_contract_missing/provider_call_id_pc_1234567890abcdef/really-long-detail-without-natural-breaks";
    await page.setContent(`<!doctype html>
      <html>
        <head>
          <style>${css}</style>
          <style>
            body { margin: 0; background: #05070b; }
            .layout-proof { width: 320px; margin: 8px; }
          </style>
        </head>
        <body>
          <main class="layout-proof">
            <article class="agent-message assistant">
              <div class="agent-timeline">
                <div class="agent-timeline-summary">
                  <span class="agent-timeline-pill objective">Objective</span>
                  <span class="agent-timeline-pill route">Route ${long}</span>
                  <span class="agent-timeline-pill current">Running hermes.progress</span>
                  <span class="agent-timeline-pill evidence">No files</span>
                  <span class="agent-timeline-pill final">Pending</span>
                </div>
                <div class="agent-timeline-rows">
                  ${Array.from({ length: 8 }, (_, index) => `
                    <div class="agent-timeline-row ${index === 2 ? "error" : "done"}">
                      <span class="agent-timeline-icon">•</span>
                      <span class="agent-timeline-label">${index === 2 ? "route_contract_missing" : "route.resolved"}</span>
                      <span class="agent-timeline-detail">${long}-${index}</span>
                    </div>
                  `).join("")}
                </div>
              </div>
              <details class="agent-token-ledger" open>
                <summary class="agent-token-ledger-summary">
                  <strong>Token ledger</strong>
                  <span class="agent-token-ledger-badge exact">exact</span>
                  <span class="agent-token-ledger-total">in 1856 out 367 total 2223 reason 19 cached 42</span>
                  <span class="agent-token-ledger-scope">quest ${long} / turn ${long} / 2 calls</span>
                </summary>
                <div class="agent-token-ledger-calls">
                  ${Array.from({ length: 3 }, (_, index) => `
                    <div class="agent-token-ledger-call exact">
                      <div class="agent-token-ledger-call-head">
                        <strong>openai-responses / gpt-5.5-${long}</strong>
                        <span>wasm-agent.avatar-chat.ui/${long}</span>
                        <code>pc_${long}_${index}</code>
                      </div>
                      <div class="agent-token-ledger-metrics">
                        <span>in 1856</span><span>out 367</span><span>cached 42</span><span>reason 19</span><span>total 2223</span>
                      </div>
                    </div>
                  `).join("")}
                </div>
              </details>
            </article>
          </main>
        </body>
      </html>`);
    const result = await page.evaluate(() => {
      const root = document.querySelector(".layout-proof");
      const rootRight = root.getBoundingClientRect().right;
      const selectors = [
        ".agent-message",
        ".agent-timeline",
        ".agent-timeline-summary",
        ".agent-timeline-rows",
        ".agent-timeline-row",
        ".agent-token-ledger",
        ".agent-token-ledger-summary",
        ".agent-token-ledger-calls",
        ".agent-token-ledger-call",
        ".agent-token-ledger-call-head",
      ];
      const overflowing = [];
      for (const selector of selectors) {
        for (const element of document.querySelectorAll(selector)) {
          const rect = element.getBoundingClientRect();
          if (rect.left < root.getBoundingClientRect().left - 1 || rect.right > rootRight + 1) {
            overflowing.push({ selector, left: rect.left, right: rect.right, rootRight });
          }
        }
      }
      return {
        documentScrollWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        overflowing,
      };
    });
    assert(result.documentScrollWidth <= result.viewportWidth, `document overflowed horizontally: ${JSON.stringify(result)}`);
    assert.deepStrictEqual(result.overflowing, []);
    console.log("agent timeline layout ok");
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
