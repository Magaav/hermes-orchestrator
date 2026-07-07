"use strict";

const fs = require("fs");
const path = require("path");
const { chromium } = require("./node_modules/playwright-core");
const { ensureSimulatorAuthUser, withAndroidShellQuery } = require("./web");

const PROMPT = "what is paracelsus in this code base and what has it done overtime";
const FOLLOWUP_PROMPT = "tell me more about this paracelsus meta-analsys and what it were doing";
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const REPORT_DIR = path.join(REPO_ROOT, "reports", "sim", "avatar-paracelsus-live", "latest");
const TARGET_URL = withAndroidShellQuery("http://127.0.0.1:8877/home?chat=wasm-agent-chat");

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiJson(url, cookie) {
  const response = await fetch(url, { headers: { cookie } });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

function chromiumExecutablePath() {
  return process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    || process.env.WASM_AGENT_SIM_CHROMIUM
    || process.env.HERMES_WASM_AGENT_CHROMIUM
    || "/snap/bin/chromium";
}

function runIdsFromEnvelopeResponses(envelopeResponses) {
  const ids = [];
  for (const item of envelopeResponses || []) {
    const text = String(item?.text || "");
    for (const line of text.split(/\n+/)) {
      if (!line.trim()) continue;
      try {
        const payload = JSON.parse(line);
        const runId = payload.run_id || payload.run?.run_id || payload.agent?.run_id || payload.provider?.run_id || "";
        if (runId) ids.push(runId);
      } catch {
        const match = line.match(/wa_run_[a-z0-9]+/);
        if (match) ids.push(match[0]);
      }
    }
  }
  return ids;
}

async function main() {
  fs.rmSync(REPORT_DIR, { recursive: true, force: true });
  fs.mkdirSync(REPORT_DIR, { recursive: true });

  const auth = ensureSimulatorAuthUser();
  if (!auth.ok || !auth.cookie) throw new Error(`sim auth failed ${JSON.stringify(auth)}`);
  const cookie = `wa_uid=${auth.cookie}`;
  const browser = await chromium.launch({
    headless: true,
    executablePath: chromiumExecutablePath(),
    args: ["--no-sandbox"],
  });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    baseURL: "http://127.0.0.1:8877",
  });
  await context.addCookies([{
    name: "wa_uid",
    value: auth.cookie,
    domain: "127.0.0.1",
    path: "/",
    httpOnly: true,
    sameSite: "Lax",
  }]);

  const page = await context.newPage();
  page.on("console", (message) => {
    fs.appendFileSync(path.join(REPORT_DIR, "console.log"), `[${message.type()}] ${message.text()}\n`);
  });
  page.on("pageerror", (error) => {
    fs.appendFileSync(path.join(REPORT_DIR, "console.log"), `[pageerror] ${error.stack || error.message}\n`);
  });
  await page.addInitScript(() => {
    try {
      for (const storage of [window.localStorage, window.sessionStorage]) {
        for (const key of Object.keys(storage)) {
          if (/wasmAgent/i.test(key) && /session|agentTargetNode|agent/i.test(key)) storage.removeItem(key);
        }
      }
      window.sessionStorage.setItem("wasmAgent.agentTargetNode.session.v1", "__target:master_frontier__");
    } catch {}
  });

  const envelopeResponses = [];
  const envelopeRequests = [];
  page.on("request", (request) => {
    try {
      if (!request.url().includes("/agent/provider/envelope")) return;
      envelopeRequests.push({
        method: request.method(),
        url: request.url(),
        postData: request.postData() || "",
      });
    } catch (error) {
      envelopeRequests.push({ url: request.url(), error: String(error) });
    }
  });
  page.on("response", async (response) => {
    try {
      if (!response.url().includes("/agent/provider/envelope")) return;
      const text = await response.text();
      envelopeResponses.push({ status: response.status(), url: response.url(), text: text.slice(0, 200000) });
    } catch (error) {
      envelopeResponses.push({ status: response.status(), url: response.url(), error: String(error) });
    }
  });

  await page.goto(TARGET_URL, { waitUntil: "domcontentloaded", timeout: 30000 });
  await page.click("#agentAvatarButton").catch(() => {});
  await page.waitForSelector("#agentInput", { state: "visible", timeout: 30000 });
  await page.waitForSelector("#agentNodeSelect", { state: "attached", timeout: 30000 });
  await page.waitForFunction(() => {
    const select = document.querySelector("#agentNodeSelect");
    return Array.from(select?.querySelectorAll?.("option") || []).some((option) => option.value === "__target:master_frontier__");
  }, null, { timeout: 45000 });
  await page.evaluate(() => {
    try {
      for (const key of Object.keys(localStorage)) {
        if (/wasmAgent/i.test(key) && /session|agent/i.test(key)) localStorage.removeItem(key);
      }
      sessionStorage.setItem("wasmAgent.agentTargetNode.session.v1", "__target:master_frontier__");
      const select = document.querySelector("#agentNodeSelect");
      if (select) {
        select.value = "__target:master_frontier__";
        select.dispatchEvent(new Event("change", { bubbles: true }));
      }
    } catch (error) {
      console.warn(`fresh-session setup failed: ${error?.message || error}`);
    }
  });
  await page.waitForFunction(() => document.querySelector("#agentNodeSelect")?.value === "__target:master_frontier__", null, { timeout: 10000 });
  await page.click("#agentSessionsButton").catch(() => {});
  await page.click("#agentNewSessionButton").catch(() => {});
  await page.waitForTimeout(500);
  const preflight = await page.evaluate(() => ({
    selected: document.querySelector("#agentNodeSelect")?.value || "",
    hasMaster: Boolean(document.querySelector('#agentNodeSelect option[value="__target:master_frontier__"]')),
    body: (document.body?.innerText || "").slice(0, 2000),
  }));

  async function waitForLatestRun(previousRunIds = new Set()) {
    let finalRunId = "";
    let finalRun = null;
    let status = "";
    const started = Date.now();
    while (Date.now() - started < 180000) {
    await sleep(1500);
    const bodyText = await page.textContent("body").catch(() => "");
    const requestSessionIds = envelopeRequests
      .map((item) => {
        try {
          return JSON.parse(item.postData || "{}").session_id || "";
        } catch {
          return "";
        }
      })
      .filter(Boolean);
    if (!finalRunId && requestSessionIds.length) {
      const sessionId = requestSessionIds[requestSessionIds.length - 1];
      const runsPayload = await apiJson(`http://127.0.0.1:8877/agent/runs?session_id=${encodeURIComponent(sessionId)}&limit=5`, cookie).catch(() => null);
      const runs = Array.isArray(runsPayload?.runs) ? runsPayload.runs : [];
      const candidate = runs.find((run) => run?.run_id && !previousRunIds.has(run.run_id));
      finalRunId = candidate?.run_id || finalRunId;
    }
    const responseRunIds = runIdsFromEnvelopeResponses(envelopeResponses);
    finalRunId = responseRunIds.reverse().find((runId) => runId && !previousRunIds.has(runId)) || finalRunId;
    if (finalRunId) {
      finalRun = await apiJson(`http://127.0.0.1:8877/agent/runs/${finalRunId}`, cookie).catch(() => null);
      status = finalRun?.run?.status || finalRun?.status || "";
      if (["completed", "failed", "cancelled"].includes(status)) break;
    }
    }
    return { finalRunId, finalRun, status };
  }

  await page.fill("#agentInput", PROMPT);
  await page.click("#agentSendButton");
  const firstTurn = await waitForLatestRun(new Set());
  if (firstTurn.status !== "completed") throw new Error(`first turn did not complete: ${JSON.stringify(firstTurn)}`);

  await page.fill("#agentInput", FOLLOWUP_PROMPT);
  await page.click("#agentSendButton");
  let { finalRunId, finalRun, status } = await waitForLatestRun(new Set([firstTurn.finalRunId]));

  const bodyText = await page.textContent("body").catch(() => "");
  if (!finalRunId) {
    const responseRunIds = runIdsFromEnvelopeResponses(envelopeResponses);
    finalRunId = responseRunIds.reverse().find((runId) => runId && runId !== firstTurn.finalRunId) || "";
  }
  if (finalRunId && !finalRun) {
    finalRun = await apiJson(`http://127.0.0.1:8877/agent/runs/${finalRunId}`, cookie).catch(() => null);
    status = finalRun?.run?.status || finalRun?.status || status;
  }
  const sessionState = { body: String(bodyText || "").slice(0, 12000) };
  const streamText = envelopeResponses.map((item) => item.text || "").join("\n");
  const userPromptSeen = (String(bodyText || "").includes(PROMPT) || streamText.includes(PROMPT))
    && (String(bodyText || "").includes(FOLLOWUP_PROMPT) || streamText.includes(FOLLOWUP_PROMPT));
  const assistantReply = String(bodyText || "");
  const final = finalRun?.run?.final || finalRun?.final || {};
  const reply = final.reply || assistantReply;
  const tokenUsage = final?.diagnostics?.token_usage || final?.diagnostics?.token_usage_head || final?.provider?.usage || {};
  const tokenTotal = Number(tokenUsage.total_tokens || tokenUsage.total || 0);
  const events = finalRunId ? await apiJson(`http://127.0.0.1:8877/agent/runs/${finalRunId}/events`, cookie).catch((error) => ({ error: String(error) })) : null;
  const finalEvents = events?.events || events || [];
  const finalObjective = (Array.isArray(finalEvents) ? finalEvents : [])
    .find((event) => event?.type === "envelope.created")?.summary || "";
  const eventText = JSON.stringify(events || {});
  const stale = /\bneed (?:a )?bounded\b|\brequires bounded\b|not inspected Paracelsus yet|cannot honestly say[\s\S]{0,180}without collecting|cannot truthfully summarize[\s\S]{0,180}(until|without)[\s\S]{0,120}inspect|should not claim[\s\S]{0,160}without inspecting/i.test(reply);
  const checks = {
    completed: status === "completed",
    selectedMaster: preflight.selected === "__target:master_frontier__" || preflight.hasMaster,
    exactPrompt: userPromptSeen,
    followupPrompt: userPromptSeen && finalObjective === FOLLOWUP_PROMPT,
    noHermes: !/hermes\.dispatch/.test(eventText),
    paracelsusRoute: /hermes-node\.paracelsus\.runtime/.test(eventText + reply),
    kernelInspect: /kernel\.inspect/.test(eventText),
    llmComposed: tokenTotal > 0 && /provider_exact|llm_api_call|openai_codex_direct|openai_responses_direct/i.test(JSON.stringify(final)),
    bootstrap: /bootstrapped_at=2026-04-24T21:41:55Z|2026-04-24T21:41:55Z|bootstrapped around `?2026-04-24T21:41:55Z`?/i.test(reply + eventText),
    dataRoot: /\/local\/datas\/paracelsus/.test(reply),
    semanticIdentity: /Hermes agent\/runtime node|Hermes/i.test(reply) && /scientific paper|meta-analysis|DCI/i.test(reply),
    conversationEvidence: /sessions=\d+|messages=\d+|15`? sessions|330`? messages|Conversation\/runtime memory evidence/i.test(reply),
    dataInvestigation: /raw_paper_json_count=\d+|summary_md_count=\d+|68`? summary|68`? raw paper|15`? PDFs?|semantic evidence|table evidence/i.test(reply),
    metaAnalysisDetail: /OpenAlex|CrossRef|PubMed|ArXiv|literature|paper summaries|raw paper JSON|PDFs?|scientific-paper-meta-analysis/i.test(reply),
    noStaleNeedInspect: !stale,
  };

  await page.screenshot({ path: path.join(REPORT_DIR, "final.png"), fullPage: true }).catch(() => {});
  await browser.close();

  const result = {
    reportDir: REPORT_DIR,
    run_id: finalRunId,
    status,
    preflight,
    checks,
    reply,
    session: sessionState,
    envelopeRequests,
    envelopeResponses,
    events,
  };
  fs.writeFileSync(path.join(REPORT_DIR, "result.json"), JSON.stringify(result, null, 2));
  fs.writeFileSync(path.join(REPORT_DIR, "summary.md"), `# Avatar Paracelsus Live\n\nrun_id: ${finalRunId}\nstatus: ${status}\nchecks: ${JSON.stringify(checks, null, 2)}\n\n## Reply\n\n${reply}\n`);
  console.log(JSON.stringify({ reportDir: REPORT_DIR, run_id: finalRunId, status, checks, reply_head: reply.slice(0, 1600) }, null, 2));
  if (!Object.values(checks).every(Boolean)) process.exit(2);
}

main().catch((error) => {
  fs.mkdirSync(REPORT_DIR, { recursive: true });
  fs.writeFileSync(path.join(REPORT_DIR, "error.txt"), error.stack || String(error));
  console.error(error.stack || error);
  process.exit(1);
});
