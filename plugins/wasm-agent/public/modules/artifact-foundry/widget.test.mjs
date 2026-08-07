import assert from "node:assert/strict";
import fs from "node:fs/promises";

const root = new URL("./", import.meta.url);
const entry = await fs.readFile(new URL("./artifact-foundry.entry.js", root), "utf8");
const worker = await fs.readFile(new URL("./artifact-foundry.worker.js", root), "utf8");
const html = await fs.readFile(new URL("./artifact-foundry.html", root), "utf8");
const styles = await fs.readFile(new URL("./artifact-foundry.css", root), "utf8");
const registry = await fs.readFile(new URL("../app-registry.js", root), "utf8");

assert.match(entry, /new Worker\(.+type: "module"/s);
assert.match(entry, /seed: seed\.slice\(\)\.buffer/);
assert.match(entry, /artifact-foundry-complete/);
assert.match(worker, /generateArtifact/);
assert.match(worker, /\[result\.output\.buffer\]/);
assert.match(html, /aria-live="polite"/);
assert.match(html, /Procedural generation only/);
assert.match(styles, /\.artifact-foundry-scroll-host[\s\S]*touch-action: pan-y/);
assert.match(registry, /id: "artifact-foundry"/);
assert.match(registry, /home: \["asolaria", "artifact-foundry"\]/);

console.log("artifact foundry widget tests passed");
