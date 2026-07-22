const STORAGE_KEY = "wasmAgent.metaAnalysis.v1";
const META_ANALYSIS_SKILL_ID = "scientific-paper-meta-analysis";
const INTEGRITY_SIGNAL_GROUPS = [
  {
    id: "funding",
    label: "Industry funding / COI",
    weight: 3,
    terms: ["industry funded", "sponsored by", "funded by", "pharmaceutical", "pharma", "conflict of interest", "consultant", "advisory board", "honoraria", "employee of", "stock", "equity"],
    negation: ["no industry funding", "no pharmaceutical funding", "no conflict of interest", "no funding", "unfunded", "independent funding", "no commercial funding"],
  },
  {
    id: "design",
    label: "Design weakness",
    weight: 2,
    terms: ["open label", "single arm", "observational", "retrospective", "post hoc", "subgroup", "underpowered", "small sample", "short follow-up", "early termination"],
    negation: [],
  },
  {
    id: "endpoint",
    label: "Endpoint / reporting risk",
    weight: 2,
    terms: ["surrogate endpoint", "composite endpoint", "relative risk", "no absolute risk", "secondary endpoint", "exploratory", "p value", "selective reporting"],
    negation: [],
  },
  {
    id: "replication",
    label: "Replication gap",
    weight: 2,
    terms: ["not replicated", "no independent replication", "single center", "unverified", "preprint", "unpublished", "abstract only"],
    negation: [],
  },
  {
    id: "safety",
    label: "Safety opacity",
    weight: 2,
    terms: ["adverse events", "serious adverse", "withdrawal", "dropout", "missing data", "loss to follow-up", "safety signal"],
    negation: [],
  },
  {
    id: "favorable",
    label: "Integrity support",
    weight: -2,
    terms: ["independent replication", "public funding", "preregistered", "registered protocol", "data sharing", "intention-to-treat", "absolute risk", "confidence interval", "systematic review"],
  },
];

function migrateState(raw) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const version = raw._v || 0;
  let migrated = raw;
  // v1: ensure required fields exist
  if (version < 1) {
    migrated = { ...migrated, _v: 1 };
  }
  return migrated;
}

function readState() {
  try {
    const raw = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return migrateState(raw);
  } catch (e) {
    console.warn("[meta-analysis] Failed to read state; starting fresh:", e?.message || e);
    return {};
  }
}

function writeState(state) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch (e) {
    console.error("[meta-analysis] Failed to write state; changes may be lost:", e?.message || e);
  }
}

function subjectId(subject) {
  return String(subject || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || `subject-${Date.now()}`;
}

function normalizeQueue(rawQueue, state = {}) {
  const savedResults = state.subjectResults && typeof state.subjectResults === "object" ? state.subjectResults : {};
  const queue = Array.isArray(rawQueue) ? rawQueue : [];
  return queue
    .map((item) => {
      if (typeof item === "string") {
        const subject = item.trim();
        if (!subject) return null;
        const id = subjectId(subject);
        return {
          id,
          subject,
          collapsed: Boolean(state.collapsedSubjects?.[id]),
          result: savedResults[id] || (state.last_subject === subject ? state.results || "" : ""),
        };
      }
      if (item && typeof item === "object") {
        const subject = String(item.subject || item.title || item.id || "").trim();
        if (!subject) return null;
        const id = String(item.id || subjectId(subject));
        return {
          id,
          subject,
          collapsed: Boolean(item.collapsed),
          result: String(item.result || savedResults[id] || ""),
        };
      }
      return null;
    })
    .filter(Boolean);
}

function assessIntegrity(text) {
  const clean = String(text || "").toLowerCase();
  const signals = [];
  let risk = 0;
  INTEGRITY_SIGNAL_GROUPS.forEach((group) => {
    const matches = group.terms.filter((term) => clean.includes(term));
    if (!matches.length) return;
    signals.push({ id: group.id, label: group.label, matches: matches.slice(0, 4), weight: group.weight });
    risk += group.weight > 0 ? group.weight + Math.min(matches.length - 1, 2) : group.weight;
  });
  const riskScore = Math.max(0, Math.min(10, risk));
  const level = riskScore >= 7 ? "high" : riskScore >= 4 ? "review" : "low";
  const missing = [
    ["funding", "funding/COI statement"],
    ["preregister", "preregistration/protocol"],
    ["absolute risk", "absolute effect size"],
    ["adverse", "safety/adverse-event accounting"],
    ["replication", "independent replication"],
  ].filter(([needle]) => !clean.includes(needle)).map(([, label]) => label);
  return { score: riskScore, level, signals, missing };
}

function integrityLabel(level) {
  if (level === "high") return "High bias risk";
  if (level === "review") return "Needs bias review";
  return "Lower flagged risk";
}

async function postJson(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Accept": "application/json" },
    credentials: "same-origin",
    body: JSON.stringify(body),
  });
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch {
    payload = { ok: false, error: { message: text.slice(0, 600) } };
  }
  if (!response.ok || payload.ok === false) {
    const message = payload?.error?.message || payload?.message || `HTTP ${response.status}`;
    throw new Error(message);
  }
  return payload;
}

function initMetaAnalysisWidget() {
  const input = document.getElementById("metaAnalysisInput");
  const rankBtn = document.getElementById("metaAnalysisRankButton");
  const exportBtn = document.getElementById("metaAnalysisExportButton");
  const queueEl = document.getElementById("metaAnalysisQueue");
  const resultsEl = document.getElementById("metaAnalysisResults");
  const statusEl = document.getElementById("metaAnalysisStatus");
  if (!input || !rankBtn || !exportBtn || !queueEl || !resultsEl || !statusEl) return;

  const state = readState();
  let queue = normalizeQueue(state.queue, state);
  let busy = false;

  function persist(extra = {}) {
    const subjectResults = Object.fromEntries(queue.filter((item) => item.result).map((item) => [item.id, item.result]));
    writeState({
      ...readState(),
      ...extra,
      queue,
      subjectResults,
      collapsedSubjects: Object.fromEntries(queue.map((item) => [item.id, Boolean(item.collapsed)])),
    });
  }

  function renderQueue() {
    if (!queue.length) {
      queueEl.innerHTML = "<em>No subjects queued.</em>";
      return;
    }
    queueEl.innerHTML = queue
      .map((item, i) => {
        const integrity = assessIntegrity(item.result);
        const badge = item.result ? `<span class="ma-integrity-badge" data-level="${integrity.level}">${integrity.score}/10 ${integrityLabel(integrity.level)}</span>` : "";
        return `
        <div class="ma-queue-item ${item.collapsed ? "is-collapsed" : ""}" data-id="${escapeHtml(item.id)}">
          <div class="ma-queue-row">
            <button class="ma-collapse-button" data-action="toggle" data-idx="${i}" title="${item.collapsed ? "Expand" : "Minimize"} subject" aria-label="${item.collapsed ? "Expand" : "Minimize"} ${escapeHtml(item.subject)}" aria-expanded="${item.collapsed ? "false" : "true"}">${item.collapsed ? "+" : "-"}</button>
            <button class="ma-subject-button" data-action="select" data-idx="${i}" title="Use subject">${i + 1}. ${escapeHtml(item.subject)}</button>
            ${badge}
            <button data-action="remove" data-idx="${i}" title="Remove subject" aria-label="Remove ${escapeHtml(item.subject)}">x</button>
          </div>
          ${item.collapsed ? "" : `<pre class="ma-subject-result">${escapeHtml(item.result || "No findings yet.")}</pre>`}
        </div>`;
      })
      .join("");
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function addSubject() {
    const subject = input.value.trim();
    if (!subject) return;
    const existing = queue.find((item) => item.subject.toLowerCase() === subject.toLowerCase());
    if (!existing) queue.push({ id: subjectId(subject), subject, collapsed: false, result: "" });
    persist();
    input.value = "";
    renderQueue();
  }

  function setStatus(text, mode = "") {
    statusEl.textContent = text;
    statusEl.dataset.mode = mode;
    statusEl.setAttribute("role", mode === "error" ? "alert" : "status");
    statusEl.setAttribute("aria-live", mode === "error" ? "assertive" : "polite");
  }

  async function assertParacelsusReady() {
    setStatus("Checking Paracelsus...", "busy");
    const payload = await postJson("/agent/tools/node.capabilities", {
      node_id: "paracelsus",
      route_id: "hermes-node.paracelsus.runtime",
      skill_id: META_ANALYSIS_SKILL_ID,
    });
    if (payload.ok === false || payload.can_answer === false) {
      throw new Error(payload?.error?.message || payload?.code || "Paracelsus is not available.");
    }
    if (payload?.skill?.available !== true) {
      throw new Error(`Paracelsus is missing required skill ${META_ANALYSIS_SKILL_ID}.`);
    }
    return payload;
  }

  function currentSubject() {
    const typed = input.value.trim();
    if (typed) return typed;
    return queue.find((item) => !item.collapsed)?.subject || queue[0]?.subject || "";
  }

  function recordSubjectResult(subject, result) {
    const id = subjectId(subject);
    let item = queue.find((entry) => entry.id === id || entry.subject.toLowerCase() === subject.toLowerCase());
    if (!item) {
      item = { id, subject, collapsed: false, result: "" };
      queue.unshift(item);
    }
    item.result = result;
    item.collapsed = false;
    persist({ results: result, last_subject: subject });
    renderQueue();
  }

  function recordSubjectFailure(subject, error, stage = "ranking") {
    const message = error?.message || "unknown backend error";
    const failureText = [
      `Status: ${stage} failed`,
      "",
      "No ranked findings were produced for this subject.",
      "",
      `Reason: ${message}`,
      "",
      "Next diagnostic checks:",
      "- Confirm Paracelsus node.capabilities reports can_answer=true.",
      "- Confirm node.chat returns non-empty reply content.",
      "- Retry after the wasm-agent backend has been restarted with the latest Master:frontier repair loop.",
      "",
      `[proof node=paracelsus source=widget-error stage=${stage} error=${message.slice(0, 160).replace(/\s+/g, "_")}]`,
    ].join("\n");
    resultsEl.textContent = failureText;
    recordSubjectResult(subject, failureText);
    return failureText;
  }

  async function rankSubject() {
    if (busy) return;
    const subject = currentSubject();
    if (!subject) {
      setStatus("Enter a subject first.", "warn");
      input.focus();
      return;
    }
    if (!queue.some((item) => item.subject.toLowerCase() === subject.toLowerCase())) {
      queue.unshift({ id: subjectId(subject), subject, collapsed: false, result: "" });
      persist();
      renderQueue();
    }
    busy = true;
    rankBtn.disabled = true;
    exportBtn.disabled = true;
    setStatus(`Paracelsus ranking: ${subject}`, "busy");
    try {
      const caps = await assertParacelsusReady();
      const payload = await postJson("/agent/tools/node.chat", {
        node_id: "paracelsus",
        route_id: "hermes-node.paracelsus.runtime",
        skill_id: META_ANALYSIS_SKILL_ID,
        objective: [
          `Use the required ${META_ANALYSIS_SKILL_ID} skill and its bundled pipeline for this subject.`,
          `Subject: ${subject}`,
          "Preserve the original subject, normalize likely terminology or identifier typos, and show the normalized query.",
          "If a literal query is empty, try corrected terminology and broader academic synonyms before reporting no results.",
          "Return a compact ranked list of papers with title, source/year if known, why it matters, and thesis/protocol notes.",
          "Add an Evidence Integrity layer for every top paper: funding/COI, sponsor role, preregistration/protocol, absolute vs relative effect, endpoint type, adverse-event accounting, dropout/missing-data risk, and independent replication.",
          "Separate journal prestige from trust. Downgrade industry-funded, sponsor-authored, surrogate-endpoint, selectively reported, or non-replicated findings even when the journal is top tier.",
          "Do not call a paper false unless the evidence proves it. Use labels: lower concern, needs bias review, high bias risk, or insufficient disclosure.",
          "Prefer evidence from your available tools and memory. If live search is unavailable, say exactly what evidence was used and what remains unverified.",
        ].join("\n"),
        timeout_sec: 240,
      });
      const reply = String(payload.reply || "").trim();
      if (!reply || /returned an empty assistant response/i.test(reply)) {
        throw new Error("Paracelsus returned no usable findings.");
      }
      if (payload?.skill?.used !== true) {
        throw new Error(`Paracelsus did not prove ${META_ANALYSIS_SKILL_ID} was loaded.`);
      }
      const proof = [
        `node=${payload.node_id || "paracelsus"}`,
        `source=${payload.source || "unknown"}`,
        `ready=${caps.can_answer !== false}`,
        `skill=${payload.skill.id}`,
        `skill_used=${payload.skill.used}`,
        `model=${payload?.usage?.model || ""}`,
        `tokens=${payload?.usage?.total_tokens || 0}`,
      ].filter(Boolean).join(" ");
      const resultText = `${reply}\n\n[proof ${proof}]`;
      resultsEl.textContent = resultText;
      recordSubjectResult(subject, resultText);
      setStatus("Ranked by Paracelsus.", "ok");
    } catch (error) {
      recordSubjectFailure(subject, error);
      setStatus(`Ranking failed: ${error?.message || "unknown backend error"}`, "error");
    } finally {
      busy = false;
      rankBtn.disabled = false;
      exportBtn.disabled = false;
    }
  }

  rankBtn.addEventListener("click", rankSubject);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") rankSubject();
  });

  queueEl.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-idx]");
    if (!btn) return;
    const idx = parseInt(btn.dataset.idx, 10);
    const item = queue[idx];
    if (!item) return;
    const action = btn.dataset.action || "remove";
    if (action === "toggle") {
      item.collapsed = !item.collapsed;
      persist();
      renderQueue();
      return;
    }
    if (action === "select") {
      input.value = item.subject;
      resultsEl.textContent = item.result || "";
      input.focus();
      return;
    }
    queue.splice(idx, 1);
    persist();
    renderQueue();
  });

  function markdownDocument() {
    const generated = new Date().toISOString();
    const sections = queue
      .filter((item) => item.result)
      .map((item, index) => {
        const integrity = assessIntegrity(item.result);
        const signalText = integrity.signals.length
          ? integrity.signals.map((signal) => `- ${signal.label}: ${signal.matches.join(", ")}`).join("\n")
          : "- No local keyword bias signals were detected. Manual evidence review still required.";
        const missingText = integrity.missing.length ? integrity.missing.join(", ") : "No core disclosure gaps detected by local scan.";
        return `## ${index + 1}. ${item.subject}\n\n### Evidence Integrity Overlay\n\nBias risk: ${integrity.score}/10 (${integrityLabel(integrity.level)})\n\nFlagged signals:\n${signalText}\n\nMissing or unclear fields: ${missingText}\n\n### Findings\n\n${item.result.trim()}`;
      })
      .join("\n\n---\n\n");
    return [
      "# Realure Meta-Analysis Findings",
      "",
      `Generated: ${generated}`,
      "",
      sections || "_No ranked findings yet._",
      "",
    ].join("\n");
  }

  function renderFindingBlock(block) {
    const proofMatch = block.match(/\[proof\s+([^\]]+)\]\s*$/i);
    const withoutProof = proofMatch ? block.slice(0, proofMatch.index).trim() : block.trim();
    const paragraphs = withoutProof
      .split(/\n{2,}/)
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const lines = part.split("\n").map((line) => line.trim()).filter(Boolean);
        if (lines.length && lines.every((line) => /^[-*]\s+/.test(line))) {
          return `<ul>${lines.map((line) => `<li>${escapeHtml(line.replace(/^[-*]\s+/, ""))}</li>`).join("")}</ul>`;
        }
        const labelMatch = part.match(/^([^:\n]{2,48}):\s*([\s\S]+)$/);
        if (labelMatch) {
          return `<p><strong>${escapeHtml(labelMatch[1])}</strong><br>${escapeHtml(labelMatch[2]).replace(/\n/g, "<br>")}</p>`;
        }
        return `<p>${escapeHtml(part).replace(/\n/g, "<br>")}</p>`;
      })
      .join("\n");
    const proof = proofMatch ? `<aside class="proof-chip">${escapeHtml(proofMatch[1])}</aside>` : "";
    return `${paragraphs || "<p>No narrative findings yet.</p>"}${proof}`;
  }

  function renderedMarkdown(markdown) {
    return markdown
      .split(/\n{2,}/)
      .map((block) => {
        if (block.startsWith("# ")) return `<h1>${escapeHtml(block.slice(2))}</h1>`;
        if (block.startsWith("## ")) return `<h2>${escapeHtml(block.slice(3))}</h2>`;
        if (block === "---") return "<hr>";
        const lines = block.split("\n");
        if (lines.every((line) => /^[-*]\s+/.test(line))) {
          return `<ul>${lines.map((line) => `<li>${escapeHtml(line.replace(/^[-*]\s+/, ""))}</li>`).join("")}</ul>`;
        }
        return `<p>${escapeHtml(block).replace(/\n/g, "<br>")}</p>`;
      })
      .join("\n");
  }

  function exportedSubjectCards() {
    const findings = queue.filter((item) => item.result);
    if (!findings.length) return '<section class="empty-state">No ranked findings yet.</section>';
    return findings.map((item, index) => {
      const integrity = assessIntegrity(item.result);
      const signals = integrity.signals.length
        ? integrity.signals.map((signal) => `<li><strong>${escapeHtml(signal.label)}</strong>: ${escapeHtml(signal.matches.join(", "))}</li>`).join("")
        : "<li>No local keyword bias signals were detected. Manual evidence review still required.</li>";
      const missing = integrity.missing.length ? integrity.missing.join(", ") : "No core disclosure gaps detected by local scan.";
      return `
      <article class="finding-card">
        <header class="finding-head">
          <span class="finding-index">${index + 1}</span>
          <div>
            <h2>${escapeHtml(item.subject)}</h2>
            <p>Scientific paper meta-analysis finding</p>
          </div>
        </header>
        <section class="integrity-panel" data-level="${integrity.level}">
          <div><strong>${integrity.score}/10</strong><span>${integrityLabel(integrity.level)}</span></div>
          <ul>${signals}</ul>
          <p><strong>Missing or unclear:</strong> ${escapeHtml(missing)}</p>
        </section>
        <div class="finding-body">${renderFindingBlock(item.result)}</div>
      </article>
    `;
    }).join("");
  }

  function exportFindings() {
    const markdown = markdownDocument();
    const findingCount = queue.filter((item) => item.result).length;
    const subjectCount = queue.length;
    const generated = new Date().toLocaleString();
    const html = `<!doctype html>
<html><head><meta charset="utf-8"><title>Realure Meta-Analysis Findings</title>
<style>
:root{color-scheme:light;--ink:#172033;--muted:#647084;--line:#dfe6ef;--soft:#f5f8fc;--accent:#2563eb;--accent2:#0f766e}
*{box-sizing:border-box}body{font:15px/1.6 Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;margin:0;background:#eef3f8;color:var(--ink)}
.page{max-width:980px;margin:0 auto;padding:32px 24px 56px}.actions{position:sticky;top:0;z-index:2;display:flex;justify-content:flex-end;padding:12px 0;background:linear-gradient(#eef3f8 70%,rgba(238,243,248,0))}
button{border:0;border-radius:8px;background:var(--accent);color:white;padding:9px 14px;font-weight:700;box-shadow:0 8px 24px rgba(37,99,235,.18)}
.hero{border-radius:18px;background:linear-gradient(135deg,#10223f,#0f766e);color:white;padding:28px 30px;margin-bottom:18px;box-shadow:0 18px 44px rgba(15,34,63,.22)}
.eyebrow{font-size:12px;letter-spacing:.08em;text-transform:uppercase;opacity:.78;margin:0 0 8px}.hero h1{font-size:34px;line-height:1.08;margin:0 0 10px}.hero p{max-width:680px;margin:0;color:rgba(255,255,255,.82)}
.stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin:18px 0 22px}.stat{border:1px solid var(--line);border-radius:14px;background:white;padding:14px 16px}.stat strong{display:block;font-size:22px}.stat span{color:var(--muted);font-size:12px}
.finding-card{break-inside:avoid;border:1px solid var(--line);border-radius:16px;background:white;margin:14px 0;overflow:hidden;box-shadow:0 10px 30px rgba(23,32,51,.07)}
.finding-head{display:flex;gap:14px;align-items:center;padding:16px 18px;background:var(--soft);border-bottom:1px solid var(--line)}.finding-index{display:grid;place-items:center;width:34px;height:34px;border-radius:999px;background:var(--accent2);color:white;font-weight:800}.finding-head h2{font-size:19px;line-height:1.25;margin:0}.finding-head p{margin:2px 0 0;color:var(--muted);font-size:12px}
.integrity-panel{display:grid;grid-template-columns:150px minmax(0,1fr);gap:12px;padding:14px 18px;border-bottom:1px solid var(--line);background:#f8fafc}.integrity-panel[data-level=review]{background:#fffbeb}.integrity-panel[data-level=high]{background:#fff1f2}.integrity-panel strong{display:block;font-size:24px;line-height:1}.integrity-panel span{display:block;color:var(--muted);font-size:12px}.integrity-panel ul{margin:0 0 8px 18px;padding:0}.integrity-panel li{margin:3px 0}.integrity-panel p{grid-column:1/-1;margin:0;color:var(--muted);font-size:12px}
.finding-body{padding:18px}.finding-body p{margin:0 0 12px;white-space:pre-wrap}.finding-body strong{color:#0f3f74}.finding-body ul{margin:0 0 14px 20px;padding:0}.finding-body li{margin:5px 0}.proof-chip{margin-top:16px;border:1px solid #bdd7ff;background:#eff6ff;color:#1d4ed8;border-radius:12px;padding:10px 12px;font-size:12px;word-break:break-word}
.empty-state{border:1px dashed var(--line);border-radius:16px;background:white;padding:32px;text-align:center;color:var(--muted)}
.raw-md{margin-top:24px}.raw-md details{border:1px solid var(--line);border-radius:14px;background:white;padding:12px 14px}.raw-md summary{cursor:pointer;font-weight:700}.raw-md pre{white-space:pre-wrap;font-size:12px;color:#334155}
@media print{body{background:white}.page{max-width:none;padding:0}.actions{display:none}.hero,.finding-card,.stat{box-shadow:none}.hero{border-radius:0}.finding-card{page-break-inside:avoid}}
</style></head><body><main class="page"><div class="actions"><button onclick="window.print()">Print / Save PDF</button></div><section class="hero"><p class="eyebrow">Realure research export</p><h1>Meta-Analysis Findings</h1><p>Readable report generated from the Realure Meta-Analysis widget. Open this file in any browser, or print it to PDF.</p></section><section class="stats"><div class="stat"><strong>${subjectCount}</strong><span>Subjects queued</span></div><div class="stat"><strong>${findingCount}</strong><span>Findings exported</span></div><div class="stat"><strong>${escapeHtml(generated)}</strong><span>Generated</span></div></section>${exportedSubjectCards()}<section class="raw-md"><details><summary>Markdown source</summary><pre>${escapeHtml(markdown)}</pre></details></section></main></body></html>`;
    const blob = new Blob([html], { type: "text/html;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `realure-meta-analysis-${new Date().toISOString().slice(0, 10)}.html`;
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setStatus("Exported rendered findings HTML.", "ok");
  }

  exportBtn.addEventListener("click", exportFindings);

  window.__metaAnalysisWidget = {
    getQueue: () => [...queue],
    rankSubject,
    addSubject,
    exportFindings,
    setResults: (text) => {
      resultsEl.textContent = text;
      const subject = currentSubject() || "Manual finding";
      recordSubjectResult(subject, text);
    },
    clearResults: () => {
      resultsEl.textContent = "";
      queue.forEach((item) => {
        item.result = "";
      });
      persist({ results: "" });
      renderQueue();
    },
  };

  if (state.results) resultsEl.textContent = state.results;
  setStatus(state.last_subject ? `Last subject: ${state.last_subject}` : "Ready.");
  renderQueue();
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initMetaAnalysisWidget);
} else {
  initMetaAnalysisWidget();
}
