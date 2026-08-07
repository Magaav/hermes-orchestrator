const assert = require("assert");
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const modulePath = path.join(__dirname, "..", "public", "modules", "master-frontier", "change-evidence.js");
const source = fs.readFileSync(modulePath, "utf8");
const sandbox = { exports: {}, Set };
vm.runInNewContext(
  `${source
    .replace("export function masterFrontierChangeEvidence", "function masterFrontierChangeEvidence")
    .replace("export function masterFrontierChangeDiagnostics", "function masterFrontierChangeDiagnostics")
    .replace("export function renderMasterFrontierChangeEvidence", "function renderMasterFrontierChangeEvidence")}
exports.masterFrontierChangeEvidence=masterFrontierChangeEvidence;
exports.masterFrontierChangeDiagnostics=masterFrontierChangeDiagnostics;`,
  sandbox,
  { filename: modulePath }
);

const { masterFrontierChangeEvidence, masterFrontierChangeDiagnostics } = sandbox.exports;
const runFile = { path: "public/app.js", additions: 2, deletions: 1 };
const observedFile = { path: "tests/widget.test.js", additions: 4, deletions: 0 };

assert.deepStrictEqual(
  JSON.parse(JSON.stringify(masterFrontierChangeEvidence({
    changed_files: [runFile],
    diagnostics: {
      diff_seen: true,
      observed_changed_files: [runFile, observedFile],
    },
  }))),
  [
    { id: "changed", label: "Changed by this run", files: [runFile], runOwned: true },
    { id: "observed", label: "Observed worktree changes", files: [observedFile], runOwned: false },
  ],
  "run-owned and observed changes must be separate and deduplicated"
);

assert.deepStrictEqual(
  JSON.parse(JSON.stringify(masterFrontierChangeEvidence({
    diagnostics: { observed_changed_files: [observedFile] },
  }))),
  [],
  "unverified observed paths must not appear as diff evidence"
);

assert.deepStrictEqual(
  JSON.parse(JSON.stringify(masterFrontierChangeEvidence({
    diagnostics: { diff_seen: true, observed_changed_files: [observedFile] },
  }))),
  [{ id: "observed", label: "Observed worktree changes", files: [observedFile], runOwned: false }],
  "a verification-only run must expose its observed worktree diff"
);

assert(source.includes("group.runOwned && checkpoint?.ref"), "Stepback must remain restricted to run-owned changes");
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(masterFrontierChangeDiagnostics({
    observed_changed_files: [observedFile],
    observed_changed_files_complete: 1,
    diff_seen: true,
  }))),
  {
    observed_changed_files: [observedFile],
    observed_changed_files_complete: false,
    diff_seen: true,
  },
  "change diagnostics must preserve paths while keeping proof flags strict"
);
console.log("Master:frontier change evidence tests: PASS");
