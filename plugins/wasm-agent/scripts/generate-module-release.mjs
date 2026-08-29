#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const pluginRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const publicRoot = path.join(pluginRoot, "public");
const args = process.argv.slice(2);
const checkOnly = args.includes("--check");
const outputIndex = args.indexOf("--output");
if (args.some((arg, index) => !["--check", "--output"].includes(arg) && index !== outputIndex + 1)) {
  throw new Error("usage: generate-module-release.mjs [--check] [--output <path>]");
}
if (outputIndex >= 0 && !args[outputIndex + 1]) throw new Error("--output requires a path");
const outputPath = outputIndex >= 0
  ? path.resolve(process.cwd(), args[outputIndex + 1])
  : path.join(publicRoot, "module-release.json");
const roots = ["app.js", "android-app.js", "app-loader.js", "index.html", "sw.js"];

function walk(root, relative = "") {
  const absolute = path.join(root, relative);
  return fs.readdirSync(absolute, { withFileTypes: true }).flatMap((entry) => {
    const child = path.join(relative, entry.name);
    if (entry.isDirectory()) {
      if (["models", "vendor", "fixtures", "media"].includes(entry.name)) return [];
      return walk(root, child);
    }
    return /\.(?:css|js|mjs)$/.test(entry.name) && !/\.test\.m?js$/.test(entry.name) ? [child] : [];
  });
}

const files = [...roots, ...walk(path.join(publicRoot, "modules")).map((item) => `modules/${item}`)]
  .filter((item, index, values) => values.indexOf(item) === index)
  .sort();
const entries = Object.fromEntries(files.map((relative) => {
  const bytes = fs.readFileSync(path.join(publicRoot, relative));
  return [relative, crypto.createHash("sha256").update(bytes).digest("hex")];
}));
const releaseId = crypto.createHash("sha256")
  .update(files.map((file) => `${file}\0${entries[file]}\n`).join(""))
  .digest("hex");
const manifest = {
  schema: "hermes.wasm_agent.module_release.v1",
  release_id: releaseId,
  entry: { web: "app.js", android: "android-app.js" },
  files: entries,
};
const serialized = `${JSON.stringify(manifest, null, 2)}\n`;
if (checkOnly) {
  const actual = fs.existsSync(outputPath) ? fs.readFileSync(outputPath, "utf8") : "";
  if (actual !== serialized) {
    console.error(JSON.stringify({ ok: false, error: "module_release_stale", expected_release_id: releaseId, output: path.relative(pluginRoot, outputPath) }));
    process.exit(2);
  }
} else {
  fs.writeFileSync(outputPath, serialized);
}
console.log(JSON.stringify({ ok: true, mode: checkOnly ? "check" : "generate", release_id: releaseId, files: files.length, output: path.relative(pluginRoot, outputPath) }));
