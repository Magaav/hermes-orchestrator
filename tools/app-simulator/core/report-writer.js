"use strict";

const fs = require("fs");
const path = require("path");
const { redactValue } = require("./redact");

function statusIcon(status) {
  if (status === "passed") return "PASS";
  if (status === "failed") return "FAIL";
  if (status === "pending") return "PENDING";
  if (status === "running") return "RUNNING";
  return String(status || "UNKNOWN").toUpperCase();
}

function markdownEscape(value) {
  return String(value == null ? "" : value).replace(/\|/g, "\\|").replace(/\n/g, " ");
}

function summaryMarkdown(result) {
  const safe = redactValue(result);
  const lines = [];
  lines.push(`# WASM Agent Simulation: ${safe.platform}`);
  lines.push("");
  lines.push(`- Status: ${statusIcon(safe.status)}`);
  lines.push(`- Score: ${safe.score == null ? "n/a" : `${safe.score}/100`}`);
  lines.push(`- Run ID: ${safe.runId}`);
  lines.push(`- Started: ${safe.startedAt}`);
  lines.push(`- Finished: ${safe.finishedAt || ""}`);
  if (safe.target?.url) lines.push(`- Target: ${safe.target.url}`);
  if (safe.pendingReason) lines.push(`- Pending: ${safe.pendingReason}`);
  if (safe.evidence?.observations?.reportSummary) {
    lines.push("");
    lines.push("## Key Evidence");
    lines.push("");
    for (const [key, value] of Object.entries(safe.evidence.observations.reportSummary)) {
      const rendered = typeof value === "string" ? value : JSON.stringify(value);
      lines.push(`- ${markdownEscape(key)}: ${markdownEscape(rendered)}`);
    }
  }
  lines.push("");
  lines.push("## Lifecycle");
  lines.push("");
  lines.push("| Phase | Status | Detail |");
  lines.push("| --- | --- | --- |");
  for (const step of safe.lifecycle || []) {
    lines.push(`| ${markdownEscape(step.phase)} | ${markdownEscape(step.status)} | ${markdownEscape(step.detail)} |`);
  }
  lines.push("");
  lines.push("## Assertions");
  lines.push("");
  lines.push("| Assertion | Status | Detail |");
  lines.push("| --- | --- | --- |");
  for (const assertion of safe.assertions || []) {
    lines.push(`| ${markdownEscape(assertion.name)} | ${markdownEscape(assertion.status)} | ${markdownEscape(assertion.detail)} |`);
  }
  if (!safe.assertions?.length) lines.push("| none | n/a | no assertions executed |");
  lines.push("");
  lines.push("## Artifacts");
  lines.push("");
  const artifacts = safe.evidence?.artifacts || {};
  for (const [name, value] of Object.entries(artifacts)) {
    if (Array.isArray(value)) {
      for (const item of value) lines.push(`- ${name}: \`${item}\``);
    } else if (value) {
      lines.push(`- ${name}: \`${value}\``);
    }
  }
  if (!Object.keys(artifacts).length) lines.push("- none");
  lines.push("");
  lines.push("## Guardrails");
  lines.push("");
  for (const guardrail of safe.guardrails || []) lines.push(`- ${guardrail}`);
  if (safe.errors?.length) {
    lines.push("");
    lines.push("## Errors");
    lines.push("");
    for (const error of safe.errors) lines.push(`- ${markdownEscape(error.message || error)}`);
  }
  lines.push("");
  return `${lines.join("\n")}\n`;
}

function writeJson(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, `${JSON.stringify(redactValue(payload), null, 2)}\n`);
}

function writeText(filePath, payload) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, String(payload));
}

function writeReports(result, reportDir) {
  writeJson(path.join(reportDir, "result.json"), result);
  writeText(path.join(reportDir, "summary.md"), summaryMarkdown(result));
}

module.exports = {
  summaryMarkdown,
  writeJson,
  writeReports,
  writeText,
};
