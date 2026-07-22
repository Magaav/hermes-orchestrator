const assert = require("assert");
const fs = require("fs");
const path = require("path");

const pluginRoot = path.resolve(__dirname, "..");
const publicRoot = path.join(pluginRoot, "public");
const appPath = path.join(publicRoot, "app.js");
const devHmrPath = path.join(publicRoot, "modules", "hmr", "dev-hmr.js");
const serverPath = path.join(pluginRoot, "server", "static_server.py");
const appJs = fs.readFileSync(appPath, "utf8");
const devHmrJs = fs.readFileSync(devHmrPath, "utf8");
const serverPy = fs.readFileSync(serverPath, "utf8");

function staticImports(source) {
  const imports = [];
  const pattern = /(?:^|[\n;])\s*import\s+(?:(?:[\s\S]*?)\s+from\s+)?["']([^"']+)["']/g;
  let match;
  while ((match = pattern.exec(source))) {
    imports.push(match[1]);
  }
  return imports;
}

function publicUrlForFile(filePath) {
  return `/${path.relative(publicRoot, filePath).split(path.sep).join("/")}`;
}

function resolveLocalImport(fromPath, specifier) {
  if (!specifier.startsWith(".")) return null;
  const fileSpecifier = specifier.replace(/[?#].*$/, "");
  const resolved = path.resolve(path.dirname(fromPath), fileSpecifier);
  const candidates = path.extname(resolved)
    ? [resolved]
    : [`${resolved}.js`, path.join(resolved, "index.js")];
  const found = candidates.find((candidate) => fs.existsSync(candidate));
  assert(found, `auth shell static import is missing on disk: ${specifier} from ${publicUrlForFile(fromPath)}`);
  assert(found.startsWith(publicRoot + path.sep), `auth shell static import escapes public root: ${specifier}`);
  return found;
}

function collectStaticGraph(entryPath) {
  const seen = new Set();
  const edges = [];
  function visit(filePath) {
    if (seen.has(filePath)) return;
    seen.add(filePath);
    const source = fs.readFileSync(filePath, "utf8");
    for (const specifier of staticImports(source)) {
      const resolved = resolveLocalImport(filePath, specifier);
      if (!resolved) continue;
      const edge = {
        from: publicUrlForFile(filePath),
        to: publicUrlForFile(resolved),
        specifier,
      };
      edges.push(edge);
      visit(resolved);
    }
  }
  visit(entryPath);
  return edges;
}

const staticGraph = collectStaticGraph(appPath);
const rootAssetEdges = staticGraph.filter((edge) => !edge.to.startsWith("/modules/"));

assert.deepStrictEqual(
  rootAssetEdges,
  [],
  "auth shell static graph must stay inside /modules so optional root assets cannot 401 and freeze login boot"
);

assert(
  !appJs.includes('import { PROVIDER_MODEL_SNAPSHOT } from "./provider-model-catalog.js";'),
  "provider model catalog must not be a top-level import; it previously blocked login clicks when served as 401"
);
assert(
  appJs.includes("function loadDirectProviderModelSnapshot")
    && appJs.includes("import(AGENT_DIRECT_PROVIDER_MODEL_SNAPSHOT_PATH)"),
  "provider model catalog must lazy-load from provider setup after the auth shell is interactive"
);
assert(
  serverPy.includes('"/app.js"') && serverPy.includes('path.startswith("/modules/")'),
  "server public allowlist must expose the app module and module graph before authentication"
);
assert(
  serverPy.includes('"/provider-model-catalog.js"'),
  "server should still expose the lazy provider model snapshot publicly once provider setup requests it"
);
assert(
  appJs.includes("__wasmAgentAppDevHmr")
    && appJs.includes("dev_hmr_legacy_bridge_preserved")
    && !appJs.includes("window.__wasmAgentDevHmr = {"),
  "auth shell must not overwrite Electron's read-only native HMR preload bridge during login bootstrap"
);
assert(
  devHmrJs.includes("__wasmAgentAppDevHmr")
    && devHmrJs.indexOf("__wasmAgentAppDevHmr") < devHmrJs.indexOf("__wasmAgentDevHmr"),
  "dev HMR must prefer the app-owned deferral bridge before the legacy native bridge"
);

console.log("auth shell boot regression ok");
