import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL, fileURLToPath } from "node:url";
import vm from "node:vm";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(__dirname, "..");
const publicRoot = path.join(pluginRoot, "public");
const moduleCache = new Map();
const context = vm.createContext({
  URL,
  console,
  performance,
  location: { href: "https://wasm-agent.local/" },
});

async function loadBrowserModule(filePath) {
  const resolved = path.resolve(filePath);
  const identifier = pathToFileURL(resolved).href;
  if (moduleCache.has(identifier)) return moduleCache.get(identifier);
  if (!vm.SourceTextModule) {
    throw new Error("vm.SourceTextModule is unavailable; run node with --experimental-vm-modules");
  }
  const source = fs.readFileSync(resolved, "utf8");
  const module = new vm.SourceTextModule(source, { context, identifier });
  moduleCache.set(identifier, module);
  await module.link((specifier, referencingModule) => {
    const next = new URL(specifier, referencingModule.identifier);
    return loadBrowserModule(fileURLToPath(next));
  });
  await module.evaluate();
  return module;
}

const testModule = await loadBrowserModule(
  path.join(publicRoot, "modules", "chat-composer", "chat-composer.test.js")
);
const tokenizerModule = await loadBrowserModule(
  path.join(publicRoot, "modules", "chat-composer", "chat-tokenizer.js")
);
const rendererModule = await loadBrowserModule(
  path.join(publicRoot, "modules", "chat-composer", "chat-renderer.js")
);

const { runChatComposerTests } = testModule.namespace;
const { tokenizeChatMarkdown } = tokenizerModule.namespace;
const { renderChatMarkdownToHtml } = rendererModule.namespace;

const results = runChatComposerTests();
const failures = results.filter((result) => !result.ok);
assert.equal(failures.length, 0, failures.map((failure) => `${failure.id}: ${failure.error}`).join("\n"));

const raw = "`test` `t";
const before = raw;
const tokens = tokenizeChatMarkdown(raw);
assert.equal(raw, before, "tokenizer must not mutate raw strings");
assert.equal(tokens.map((token) => token.raw).join(""), raw, "token stream must preserve raw source");

const html = renderChatMarkdownToHtml("<script>alert(1)</script> javascript:alert(1)");
assert(!html.includes("<script>"), "renderer must escape script tags");
assert(!html.includes('href="javascript:'), "renderer must not link unsafe protocols");

console.log(`${results.length} chat composer module tests passed`);
