"use strict";

const fs = require("fs");
const path = require("path");

function repoRootFromCore() {
  if (process.env.WASM_AGENT_SIM_ROOT_DIR) {
    return path.resolve(process.env.WASM_AGENT_SIM_ROOT_DIR);
  }
  return path.resolve(__dirname, "..", "..", "..");
}

function reportDirFor(platform, rootDir = repoRootFromCore()) {
  return path.join(rootDir, "reports", "sim", platform, "latest");
}

function prepareReportDir(platform, rootDir = repoRootFromCore()) {
  const reportDir = reportDirFor(platform, rootDir);
  fs.rmSync(reportDir, { recursive: true, force: true });
  fs.mkdirSync(reportDir, { recursive: true });
  return reportDir;
}

function artifactPath(reportDir, ...segments) {
  const filePath = path.join(reportDir, ...segments);
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  return filePath;
}

function artifactRef(reportDir, filePath) {
  return path.relative(reportDir, filePath).split(path.sep).join("/");
}

module.exports = {
  artifactPath,
  artifactRef,
  prepareReportDir,
  repoRootFromCore,
  reportDirFor,
};
