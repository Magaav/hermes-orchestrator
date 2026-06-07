"use strict";

const { artifactPath, artifactRef, prepareReportDir, repoRootFromCore, reportDirFor } = require("./artifacts");
const { redactString, redactValue } = require("./redact");
const { scoreResult } = require("./score");
const { createResult, isoTimestamp } = require("./schema");
const { writeJson, writeReports, writeText } = require("./report-writer");

class SimulationContext {
  constructor({ platform, command, engine = null, rootDir = repoRootFromCore() }) {
    this.rootDir = rootDir;
    this.reportDir = prepareReportDir(platform, rootDir);
    this.result = createResult({ platform, command, engine });
  }

  phase(name) {
    return this.result.lifecycle.find((step) => step.phase === name);
  }

  startPhase(name, detail = "") {
    const step = this.phase(name);
    if (!step) return;
    step.status = "running";
    step.startedAt = step.startedAt || isoTimestamp();
    if (detail) step.detail = detail;
  }

  completePhase(name, status = "passed", detail = "") {
    const step = this.phase(name);
    if (!step) return;
    step.status = status;
    step.finishedAt = isoTimestamp();
    if (detail) step.detail = detail;
  }

  addAssertion(name, passed, detail = "", evidence = undefined) {
    const assertion = {
      name,
      status: passed ? "passed" : "failed",
      detail,
    };
    if (evidence !== undefined) assertion.evidence = evidence;
    this.result.assertions.push(assertion);
    return passed;
  }

  addPendingAssertion(name, detail = "", evidence = undefined) {
    const assertion = {
      name,
      status: "pending",
      detail,
    };
    if (evidence !== undefined) assertion.evidence = evidence;
    this.result.assertions.push(assertion);
    return false;
  }

  addError(error, phase = "") {
    this.result.errors.push({
      phase,
      message: redactString(error?.message || String(error)),
      name: error?.name || "",
      stack: redactString(error?.stack || "").slice(0, 2400),
    });
  }

  artifactPath(...segments) {
    return artifactPath(this.reportDir, ...segments);
  }

  artifactRef(filePath) {
    return artifactRef(this.reportDir, filePath);
  }

  addArtifact(name, filePath) {
    const ref = this.artifactRef(filePath);
    const current = this.result.evidence.artifacts[name];
    if (!current) {
      this.result.evidence.artifacts[name] = ref;
    } else if (Array.isArray(current)) {
      current.push(ref);
    } else {
      this.result.evidence.artifacts[name] = [current, ref];
    }
    return ref;
  }

  writeJsonArtifact(name, relativePath, payload) {
    const filePath = this.artifactPath(...relativePath.split("/"));
    writeJson(filePath, payload);
    this.addArtifact(name, filePath);
    return filePath;
  }

  writeTextArtifact(name, relativePath, payload) {
    const filePath = this.artifactPath(...relativePath.split("/"));
    writeText(filePath, redactString(String(payload)));
    this.addArtifact(name, filePath);
    return filePath;
  }

  score() {
    return scoreResult(this.result);
  }

  report() {
    writeReports(this.result, this.reportDir);
  }
}

module.exports = {
  SimulationContext,
  artifactPath,
  artifactRef,
  prepareReportDir,
  redactString,
  redactValue,
  reportDirFor,
  repoRootFromCore,
  scoreResult,
  writeJson,
  writeReports,
  writeText,
};
