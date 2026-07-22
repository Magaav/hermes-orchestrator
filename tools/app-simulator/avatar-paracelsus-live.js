"use strict";

const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const { chromium } = require("./node_modules/playwright-core");
const { ensureSimulatorAuthUser, withAndroidShellQuery } = require("./web");
const { evidenceToolNames, runtimeInspectWasExecuted } = require("./core/run-evidence");

const DEFAULT_PROFILE = "paracelsus";
const PROFILE = String(process.env.WASM_AGENT_SIM_LIVE_PROFILE || DEFAULT_PROFILE).trim().toLowerCase();
const PROFILE_DEFAULTS = {
  paracelsus: {
    prompt: "what is paracelsus in this code base and what has it done overtime",
    followup: "tell me more about this paracelsus meta-analsys and what it were doing",
  },
  "source-critique": {
    prompt: "critisize meta-analysis widget inside realure space",
    followup: "",
  },
  "sandbox-edit": {
    prompt: "Review the repository text at tests/fixtures/master_frontier_v5_live_sandbox.txt and report its exact current values using repository read evidence. Include this future-state note verbatim in your answer: target status=after and target proof=verified. Do not modify anything.",
    followup: "Change it.",
  },
};
const REPORT_PROFILE = Object.prototype.hasOwnProperty.call(PROFILE_DEFAULTS, PROFILE) ? PROFILE : "invalid-profile";
const profileDefaults = PROFILE_DEFAULTS[PROFILE] || PROFILE_DEFAULTS[DEFAULT_PROFILE];
const PROMPT = String(process.env.WASM_AGENT_SIM_LIVE_PROMPT || profileDefaults.prompt).trim();
const hasFollowupOverride = Object.prototype.hasOwnProperty.call(process.env, "WASM_AGENT_SIM_LIVE_FOLLOWUP_PROMPT");
const FOLLOWUP_PROMPT = String(hasFollowupOverride
  ? process.env.WASM_AGENT_SIM_LIVE_FOLLOWUP_PROMPT
  : profileDefaults.followup).trim();
const PROMPTS = [PROMPT, ...(FOLLOWUP_PROMPT ? [FOLLOWUP_PROMPT] : [])];
const REPO_ROOT = path.resolve(__dirname, "..", "..");
const REPORT_DIR = path.join(REPO_ROOT, "reports", "sim", `avatar-${REPORT_PROFILE}-live`, "latest");
const SANDBOX_RELATIVE_PATH = "tests/fixtures/master_frontier_v5_live_sandbox.txt";
const SANDBOX_PATH = path.join(REPO_ROOT, "plugins", "wasm-agent", SANDBOX_RELATIVE_PATH);
const SANDBOX_POSTIMAGE = "status=after\nproof=verified\n";
const TARGET_URL = withAndroidShellQuery("http://127.0.0.1:8877/home?chat=wasm-agent-chat");
const EVENT_PAGE_LIMIT = 240;
const EVENT_PAGE_MAX = 8;
let browser = null;

function sha256(value) {
  return crypto.createHash("sha256").update(String(value), "utf8").digest("hex");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function apiJson(url, cookie) {
  const response = await fetch(url, { headers: { cookie } });
  if (!response.ok) throw new Error(`${response.status} ${url}`);
  return response.json();
}

async function collectRunEvents(runId, cookie, expectedLastSeq) {
  const combined = [];
  let afterSeq = 0;
  let lastPayload = null;
  for (let page = 1; page <= EVENT_PAGE_MAX; page += 1) {
    const payload = await apiJson(
      `http://127.0.0.1:8877/agent/runs/${runId}/events?after_seq=${afterSeq}&limit=${EVENT_PAGE_LIMIT}`,
      cookie,
    );
    lastPayload = payload;
    const rows = Array.isArray(payload?.events) ? payload.events : [];
    combined.push(...rows);
    const nextAfterSeq = Number(payload?.next_after_seq || afterSeq);
    const reachedTerminal = expectedLastSeq > 0 && nextAfterSeq >= expectedLastSeq;
    const exhausted = expectedLastSeq <= 0 && rows.length < EVENT_PAGE_LIMIT;
    if (reachedTerminal || exhausted) {
      return {
        ...payload,
        complete: true,
        expected_last_seq: expectedLastSeq,
        page_count: page,
        events: combined,
      };
    }
    if (nextAfterSeq <= afterSeq) {
      return {
        ...(lastPayload || {}),
        ok: false,
        complete: false,
        error: "event_cursor_stalled",
        expected_last_seq: expectedLastSeq,
        page_count: page,
        events: combined,
      };
    }
    afterSeq = nextAfterSeq;
  }
  return {
    ...(lastPayload || {}),
    ok: false,
    complete: false,
    error: "event_page_limit_reached",
    expected_last_seq: expectedLastSeq,
    page_count: EVENT_PAGE_MAX,
    events: combined,
  };
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
  if (!Object.prototype.hasOwnProperty.call(PROFILE_DEFAULTS, PROFILE)) {
    throw new Error(`unsupported live profile: ${PROFILE}`);
  }
  if (!PROMPT) throw new Error("live prompt must not be empty");
  fs.rmSync(REPORT_DIR, { recursive: true, force: true });
  fs.mkdirSync(REPORT_DIR, { recursive: true });

  const auth = ensureSimulatorAuthUser();
  if (!auth.ok || !auth.cookie) throw new Error(`sim auth failed ${JSON.stringify(auth)}`);
  const cookie = `wa_uid=${auth.cookie}`;
  browser = await chromium.launch({
    headless: true,
    executablePath: chromiumExecutablePath(),
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
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

  async function waitForLatestRun(expectedPrompt, previousRunIds = new Set()) {
    let finalRunId = "";
    let finalRun = null;
    let status = "";
    const expectedSha256 = sha256(expectedPrompt);
    const started = Date.now();
    while (Date.now() - started < 180000) {
    await sleep(1500);
    const requestSessionIds = envelopeRequests
      .map((item) => {
        try {
          const request = JSON.parse(item.postData || "{}");
          return request?.envelope?.objective === expectedPrompt ? request.session_id || "" : "";
        } catch {
          return "";
        }
      })
      .filter(Boolean);
    if (!finalRunId && requestSessionIds.length) {
      const sessionId = requestSessionIds[requestSessionIds.length - 1];
      const runsPayload = await apiJson(`http://127.0.0.1:8877/agent/runs?session_id=${encodeURIComponent(sessionId)}&limit=5`, cookie).catch(() => null);
      const runs = Array.isArray(runsPayload?.runs) ? runsPayload.runs : [];
      const candidate = runs.find((run) => run?.run_id
        && !previousRunIds.has(run.run_id)
        && run?.request_summary?.message_sha256 === expectedSha256);
      finalRunId = candidate?.run_id || finalRunId;
    }
    if (finalRunId) {
      finalRun = await apiJson(`http://127.0.0.1:8877/agent/runs/${finalRunId}`, cookie).catch(() => null);
      status = finalRun?.run?.status || finalRun?.status || "";
      if (["completed", "failed", "interrupted", "cancelled"].includes(status)) break;
    }
    }
    return { finalRunId, finalRun, status };
  }

  const priorRunIds = new Set();
  const turnRuns = [];
  let finalRunId = "";
  let finalRun = null;
  let status = "";
  for (const prompt of PROMPTS) {
    await page.fill("#agentInput", prompt);
    await page.click("#agentSendButton");
    const turn = await waitForLatestRun(prompt, priorRunIds);
    if (turn.status !== "completed") throw new Error(`turn did not complete: ${JSON.stringify(turn)}`);
    finalRunId = turn.finalRunId;
    finalRun = turn.finalRun;
    status = turn.status;
    priorRunIds.add(finalRunId);
    const turnPayload = turn.finalRun?.run || turn.finalRun || {};
    turnRuns.push({
      prompt,
      run_id: turn.finalRunId,
      status: turn.status,
      session_id: String(turnPayload?.request_summary?.session_id || ""),
      turn_id: String(turnPayload?.turn_id || turnPayload?.request_summary?.turn_id || ""),
      protocol: String(turnPayload?.protocol || ""),
      verification_level: String(turnPayload?.final?.diagnostics?.verification_level || ""),
      changed_files: turnPayload?.final?.changed_files || [],
    });
  }

  const bodyText = await page.textContent("body").catch(() => "");
  if (!finalRunId) {
    const responseRunIds = runIdsFromEnvelopeResponses(envelopeResponses);
    finalRunId = responseRunIds.reverse().find(Boolean) || "";
  }
  if (finalRunId && !finalRun) {
    finalRun = await apiJson(`http://127.0.0.1:8877/agent/runs/${finalRunId}`, cookie).catch(() => null);
    status = finalRun?.run?.status || finalRun?.status || status;
  }
  const sessionState = { body: String(bodyText || "").slice(0, 12000) };
  const streamText = envelopeResponses.map((item) => item.text || "").join("\n");
  const userPromptSeen = PROMPTS.every((prompt) => String(bodyText || "").includes(prompt) || streamText.includes(prompt));
  const assistantReply = String(bodyText || "");
  const runPayload = finalRun?.run || finalRun || {};
  const final = runPayload.final || {};
  const { final: _embeddedFinal, ...run } = runPayload;
  const reply = final.reply || assistantReply;
  const diagnostics = final?.diagnostics || {};
  const tokenUsage = diagnostics.token_usage_head || final?.provider?.usage || {};
  const exactTokenUsage = diagnostics.token_usage_total || {};
  const tokenTotal = Number(exactTokenUsage.total_tokens || tokenUsage.total_tokens || tokenUsage.total || 0);
  const tokenCalls = Number(exactTokenUsage.calls || (tokenTotal > 0 ? 1 : 0));
  const expectedLastSeq = Number(runPayload?.latest_event?.seq || 0);
  const events = finalRunId
    ? await collectRunEvents(finalRunId, cookie, expectedLastSeq).catch((error) => ({
      ok: false,
      complete: false,
      error: String(error),
      expected_last_seq: expectedLastSeq,
      events: [],
    }))
    : { ok: false, complete: false, error: "run_id_missing", expected_last_seq: expectedLastSeq, events: [] };
  const finalEvents = events?.events || events || [];
  const eventList = Array.isArray(finalEvents) ? finalEvents : [];
  const finalObjective = eventList
    .find((event) => event?.type === "envelope.created")?.summary || "";
  const eventText = JSON.stringify(events || {});
  const expectedObjective = PROMPTS[PROMPTS.length - 1];
  const expectedObjectiveSha256 = sha256(expectedObjective);
  const requestSummary = runPayload.request_summary || {};
  const evidenceTools = evidenceToolNames(eventList);
  const commonChecks = {
    completed: status === "completed",
    selectedMaster: preflight.selected === "__target:master_frontier__" || preflight.hasMaster,
    exactPrompt: userPromptSeen,
    completeEvents: events.complete === true,
    exactObjective: finalObjective === Array.from(expectedObjective).slice(0, 180).join(""),
    exactObjectiveSha: requestSummary.message_sha256 === expectedObjectiveSha256,
    protocolV5: runPayload.protocol === "v5" && final.protocol === "v5",
    avatarRoute: final.route_id === "wasm-agent.avatar-chat.ui",
    noHermes: !/hermes\.dispatch/.test(eventText),
    nonemptyReply: Boolean(String(reply || "").trim()),
  };
  const stale = /\bneed (?:a )?bounded\b|\brequires bounded\b|not inspected Paracelsus yet|cannot honestly say[\s\S]{0,180}without collecting|cannot truthfully summarize[\s\S]{0,180}(until|without)[\s\S]{0,120}inspect|should not claim[\s\S]{0,160}without inspecting/i.test(reply);
  const paracelsusChecks = {
    followupPrompt: userPromptSeen && finalObjective === FOLLOWUP_PROMPT,
    paracelsusRoute: /hermes-node\.paracelsus\.runtime/.test(eventText + reply),
    kernelInspect: /kernel\.inspect/.test(eventText),
    llmComposed: tokenTotal > 0 && (exactTokenUsage.exact === true || /provider_exact|llm_api_call|openai_codex_direct|openai_responses_direct/i.test(JSON.stringify(final))),
    bootstrap: /bootstrapped_at=2026-04-24T21:41:55Z|2026-04-24T21:41:55Z|bootstrapped around `?2026-04-24T21:41:55Z`?/i.test(reply + eventText),
    dataRoot: /\/local\/datas\/paracelsus/.test(reply),
    semanticIdentity: /Hermes agent\/runtime node|Hermes/i.test(reply) && /scientific paper|meta-analysis|DCI/i.test(reply),
    conversationEvidence: /sessions=\d+|messages=\d+|15`? sessions|330`? messages|Conversation\/runtime memory evidence/i.test(reply),
    dataInvestigation: /raw_paper_json_count=\d+|summary_md_count=\d+|68`? summary|68`? raw paper|15`? PDFs?|semantic evidence|table evidence/i.test(reply),
    metaAnalysisDetail: /OpenAlex|CrossRef|PubMed|ArXiv|literature|paper summaries|raw paper JSON|PDFs?|scientific-paper-meta-analysis/i.test(reply),
    noStaleNeedInspect: !stale,
  };
  const providerBudget = diagnostics?.budget?.provider || {};
  const callBudget = diagnostics?.budget?.calls || {};
  const exactAdvisoryBudget = exactTokenUsage.exact === true
    && tokenTotal > 0
    && tokenTotal <= 20000
    && tokenCalls > 0
    && tokenCalls <= 6
    && Number(exactTokenUsage.metered_calls) === tokenCalls
    && Number(providerBudget.used) === tokenTotal
    && Number(providerBudget.target) === 20000
    && providerBudget.over_target === false
    && providerBudget.hard === false
    && Number(callBudget.used) === tokenCalls
    && Number(callBudget.target) === 6
    && callBudget.over_target === false
    && callBudget.hard === false;
  const sourceChecks = {
    sourceGrounded: diagnostics.verification_level === "source"
      && Array.isArray(diagnostics.files_read)
      && diagnostics.files_read.length > 0,
    sourceToolsOnly: evidenceTools.length > 0
      && evidenceTools.includes("search")
      && evidenceTools.includes("read")
      && evidenceTools.every((tool) => tool === "search" || tool === "read"),
    noRuntimeInspect: !runtimeInspectWasExecuted(eventList),
    noCommandFailure: !eventList.some((event) => event?.type === "command.failed"),
    noSemanticStall: !/no_semantic_progress/.test(eventText + JSON.stringify(final)),
    exactAdvisoryBudget,
    noChangedFiles: Array.isArray(final.changed_files) && final.changed_files.length === 0,
  };
  const changedPaths = (Array.isArray(final.changed_files) ? final.changed_files : [])
    .map((item) => String(typeof item === "string" ? item : item?.path || ""))
    .filter(Boolean);
  const routeEvent = eventList.find((event) => event?.type === "route.resolved") || {};
  const taskContract = routeEvent?.payload?.route_contract?.task_contract || {};
  const lineage = taskContract?.lineage || {};
  const requiredMutationTools = ["read", "edit", "test", "diff", "prove"];
  let sandboxPostimage = "";
  try { sandboxPostimage = fs.readFileSync(SANDBOX_PATH, "utf8"); } catch {}
  const sandboxChecks = {
    twoCompletedTurns: turnRuns.length === 2 && turnRuns.every((turn) => turn.status === "completed" && turn.protocol === "v5"),
    sameSession: turnRuns.length === 2 && Boolean(turnRuns[0].session_id) && turnRuns[0].session_id === turnRuns[1].session_id,
    groundedParent: turnRuns[0]?.verification_level === "source" && Array.isArray(turnRuns[0]?.changed_files) && turnRuns[0].changed_files.length === 0,
    inheritedImplementation: taskContract.request_class === "implementation"
      && taskContract.authority_source === "grounded_task_lineage"
      && lineage.kind === "grounded_followup_action"
      && lineage.parent_turn_id === turnRuns[0]?.turn_id,
    mutationToolChain: requiredMutationTools.every((tool) => evidenceTools.includes(tool))
      && requiredMutationTools.every((tool, index) => index === 0 || evidenceTools.indexOf(requiredMutationTools[index - 1]) < evidenceTools.indexOf(tool)),
    proofComplete: diagnostics.verification_level === "proof"
      && diagnostics.checks_passed === true
      && diagnostics.diff_seen === true
      && diagnostics.proof_seen === true,
    onlySandboxChanged: changedPaths.length === 1 && changedPaths[0] === SANDBOX_RELATIVE_PATH,
    exactSandboxPostimage: sandboxPostimage === SANDBOX_POSTIMAGE,
    noRuntimeInspect: !runtimeInspectWasExecuted(eventList),
    noHermesMutation: !/hermes\.dispatch/.test(eventText),
    noCommandFailure: !eventList.some((event) => event?.type === "command.failed"),
    noSemanticStall: !/no_semantic_progress/.test(eventText + JSON.stringify(final)),
    exactAdvisoryBudget,
  };
  const checks = {
    ...commonChecks,
    ...(PROFILE === "source-critique" ? sourceChecks : PROFILE === "sandbox-edit" ? sandboxChecks : paracelsusChecks),
  };

  await page.screenshot({ path: path.join(REPORT_DIR, "final.png"), fullPage: true }).catch(() => {});

  const result = {
    reportDir: REPORT_DIR,
    profile: PROFILE,
    prompts: PROMPTS,
    expected_objective_sha256: expectedObjectiveSha256,
    run_id: finalRunId,
    status,
    preflight,
    checks,
    turnRuns,
    sandbox: PROFILE === "sandbox-edit" ? {
      path: SANDBOX_RELATIVE_PATH,
      postimage: sandboxPostimage,
      expected_postimage_sha256: sha256(SANDBOX_POSTIMAGE),
      actual_postimage_sha256: sha256(sandboxPostimage),
    } : undefined,
    run,
    final,
    reply,
    session: sessionState,
    envelopeRequests,
    envelopeResponses,
    events,
  };
  fs.writeFileSync(path.join(REPORT_DIR, "result.json"), JSON.stringify(result, null, 2));
  fs.writeFileSync(path.join(REPORT_DIR, "summary.md"), `# Avatar ${PROFILE} Live\n\nrun_id: ${finalRunId}\nstatus: ${status}\nobjective_sha256: ${expectedObjectiveSha256}\nchecks: ${JSON.stringify(checks, null, 2)}\n\n## Reply\n\n${reply}\n`);
  console.log(JSON.stringify({ reportDir: REPORT_DIR, run_id: finalRunId, status, checks, reply_head: reply.slice(0, 1600) }, null, 2));
  if (!Object.values(checks).every(Boolean)) process.exitCode = 2;
}

main().catch((error) => {
  fs.mkdirSync(REPORT_DIR, { recursive: true });
  fs.writeFileSync(path.join(REPORT_DIR, "error.txt"), error.stack || String(error));
  console.error(error.stack || error);
  process.exitCode = 1;
}).finally(async () => {
  if (browser) await browser.close().catch(() => {});
});
