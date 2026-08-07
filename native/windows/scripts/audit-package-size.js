#!/usr/bin/env node
const fs = require("node:fs");
const path = require("node:path");

const windowsRoot = path.resolve(__dirname, "..");
const defaultRoot = path.join(windowsRoot, "release", "win-unpacked");
const targetRoot = path.resolve(process.argv[2] || defaultRoot);
const thresholdMb = Number(process.env.WASM_AGENT_WINDOWS_INSTALLER_WARN_MB || "400");
const allowedResourceOwners = new Set(["app.asar", "bridge-ops", "elevate.exe", "horc", "icon.ico", "native-defaults.json", "wasm-agent-launcher.exe"]);

function walk(root) {
  const files = [];
  const stack = [root];
  while (stack.length) {
    const current = stack.pop();
    let entries = [];
    try {
      entries = fs.readdirSync(current, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const fullPath = path.join(current, entry.name);
      if (entry.isDirectory()) stack.push(fullPath);
      else if (entry.isFile()) {
        const stat = fs.statSync(fullPath);
        files.push({ path: fullPath, relative: path.relative(root, fullPath).replace(/\\/g, "/"), size: stat.size });
      }
    }
  }
  return files;
}

function add(map, key, size) {
  map.set(key, (map.get(key) || 0) + size);
}

function mb(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function fileType(relative) {
  const ext = path.extname(relative).toLowerCase();
  return ext || "(none)";
}

function topDirectory(relative) {
  return relative.split("/")[0] || ".";
}

function suspiciousReason(relative) {
  const lower = relative.toLowerCase();
  if (/native\/releases\/windows\/.*\.(exe|blockmap)$/.test(lower)) return "old installer/update artifact";
  if (/\.apk$/.test(lower)) return "bundled APK";
  if (/platform-tools|adb\.exe/.test(lower)) return "platform-tools/ADB bundle";
  if (/reports|diagnostics|screenshots|\.log$/.test(lower)) return "debug/proof artifact";
  if (/node_modules/.test(lower)) return "node_modules payload";
  if (/\.(map|pdb|dSYM|sym)$/.test(lower)) return "map/symbol file";
  if (/cache|\.cache|build-cache/.test(lower)) return "build cache";
  return "";
}

function forbiddenPayloadReason(relative) {
  const lower = relative.toLowerCase();
  if (lower.startsWith("resources/public/")) return "cloud PWA or on-demand model tree";
  if (/\.apk$/.test(lower)) return "Android APK must be downloaded from the release feed";
  if (/\.(onnx|tflite)$/.test(lower)) return "model must be downloaded on demand";
  if (/native\/releases\/windows\/.*\.(exe|blockmap)$/.test(lower)) return "old Windows release artifact";
  return "";
}

function unexpectedResourceOwner(relative) {
  if (!relative.toLowerCase().startsWith("resources/")) return "";
  const owner = relative.split("/")[1] || "";
  return allowedResourceOwners.has(owner) ? "" : owner || "(empty)";
}

function sortedEntries(map) {
  return Array.from(map.entries()).sort((a, b) => b[1] - a[1]);
}

if (!fs.existsSync(targetRoot)) {
  console.error(`Package root not found: ${targetRoot}`);
  process.exit(1);
}

const files = walk(targetRoot);
const total = files.reduce((sum, item) => sum + item.size, 0);
const byDir = new Map();
const byType = new Map();
const suspicious = [];
const forbidden = [];
const unexpectedResources = [];
for (const file of files) {
  add(byDir, topDirectory(file.relative), file.size);
  add(byType, fileType(file.relative), file.size);
  const reason = suspiciousReason(file.relative);
  if (reason) suspicious.push({ ...file, reason });
  const forbiddenReason = forbiddenPayloadReason(file.relative);
  if (forbiddenReason) forbidden.push({ ...file, reason: forbiddenReason });
  const unexpectedOwner = unexpectedResourceOwner(file.relative);
  if (unexpectedOwner) unexpectedResources.push({ ...file, owner: unexpectedOwner });
}

const report = {
  schema: "hermes.wasm_agent.windows_package_inventory_audit.v1",
  ok: forbidden.length === 0 && unexpectedResources.length === 0,
  packageRoot: targetRoot,
  generatedAt: new Date().toISOString(),
  totalBytes: total,
  totalMb: Number((total / 1024 / 1024).toFixed(1)),
  thresholdMb,
  allowedResourceOwners: Array.from(allowedResourceOwners).sort(),
  fileCount: files.length,
  byTopDirectory: sortedEntries(byDir).map(([name, bytes]) => ({ name, bytes, mb: Number((bytes / 1024 / 1024).toFixed(1)) })),
  byFileType: sortedEntries(byType).map(([type, bytes]) => ({ type, bytes, mb: Number((bytes / 1024 / 1024).toFixed(1)) })),
  topFiles: files.slice().sort((a, b) => b.size - a.size).slice(0, 20).map((item) => ({ path: item.relative, bytes: item.size, mb: Number((item.size / 1024 / 1024).toFixed(1)) })),
  suspicious: suspicious.sort((a, b) => b.size - a.size).slice(0, 50).map((item) => ({ path: item.relative, bytes: item.size, mb: Number((item.size / 1024 / 1024).toFixed(1)), reason: item.reason })),
  forbidden: forbidden.sort((a, b) => b.size - a.size).map((item) => ({ path: item.relative, bytes: item.size, reason: item.reason })),
  unexpectedResources: unexpectedResources.sort((a, b) => a.path.localeCompare(b.path)).map((item) => ({ path: item.relative, owner: item.owner })),
};

const reportPath = path.join(windowsRoot, "release", "windows-package-size-report.json");
fs.mkdirSync(path.dirname(reportPath), { recursive: true });
fs.writeFileSync(reportPath, `${JSON.stringify(report, null, 2)}\n`);

console.log(`Windows package size audit: ${mb(total)} across ${files.length} files`);
console.log(`Report: ${reportPath}`);
console.log("Top 20 largest included files:");
for (const item of report.topFiles) {
  console.log(`${item.mb.toFixed(1).padStart(8)} MB  ${item.path}`);
}
if (report.suspicious.length) {
  console.log("Suspicious payload candidates:");
  for (const item of report.suspicious.slice(0, 20)) {
    console.log(`${item.mb.toFixed(1).padStart(8)} MB  ${item.path}  (${item.reason})`);
  }
}
if (thresholdMb > 0 && report.totalMb > thresholdMb) {
  console.warn(`WARNING: Windows package exceeds ${thresholdMb} MB threshold (${report.totalMb} MB).`);
}
if (report.forbidden.length) {
  console.error(`ERROR: Windows package contains ${report.forbidden.length} forbidden payload(s).`);
  for (const item of report.forbidden) console.error(`  ${item.path}: ${item.reason}`);
}
if (report.unexpectedResources.length) {
  console.error(`ERROR: Windows package contains ${report.unexpectedResources.length} resource(s) without a declared owner.`);
  for (const item of report.unexpectedResources) console.error(`  ${item.path}: undeclared owner ${item.owner}`);
}
if (!report.ok) {
  process.exit(1);
}
