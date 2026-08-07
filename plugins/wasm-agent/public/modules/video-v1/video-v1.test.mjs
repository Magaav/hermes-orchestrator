import assert from "node:assert/strict";
import fs from "node:fs/promises";

const contractSource = await fs.readFile(new URL("./media-contract.js", import.meta.url), "utf8");
const contractUrl = `data:text/javascript;base64,${Buffer.from(contractSource).toString("base64")}`;
const { bitratePlan, encodedDimensions, normalizeRange, resolvedOutputDuration, sourceVideoSupport, validateOutput, VIDEO_V1_LIMITS } = await import(contractUrl);
const zipSource = await fs.readFile(new URL("./zip-store.js", import.meta.url), "utf8");
const { buildStoreZip } = await import(`data:text/javascript;base64,${Buffer.from(zipSource).toString("base64")}`);

assert.deepEqual(encodedDimensions(1080, 1920), { width: 720, height: 1280 });
assert.deepEqual(encodedDimensions(1920, 1080), { width: 1280, height: 720 });
assert.deepEqual(encodedDimensions(1080, 1080), { width: 720, height: 720 });
const other = encodedDimensions(1600, 1000);
assert.ok(other.width * other.height <= 921_600);
assert.ok(other.width <= 1280 && other.height <= 1280);
assert.deepEqual(normalizeRange(8, 40, 60), { start: 8, end: 28, duration: 20 });
assert.deepEqual(normalizeRange(-2, 3, 12), { start: 0, end: 3, duration: 3 });
assert.deepEqual(normalizeRange(4, 4.2, 12), { start: 4, end: 5, duration: 1 });
assert.equal(resolvedOutputDuration(Infinity, 1), 1);
assert.equal(resolvedOutputDuration(0, 1), 1);
assert.equal(resolvedOutputDuration(0.84, 1), 0.84);
assert.deepEqual(sourceVideoSupport({ type: "video/webm" }, () => "probably"), { accepted: true, reason: "probably" });
assert.deepEqual(sourceVideoSupport({ type: "video/quicktime" }, () => ""), { accepted: false, reason: "unsupported-codec" });
assert.deepEqual(sourceVideoSupport({ type: "" }, () => ""), { accepted: true, reason: "decode-probe" });
assert.deepEqual(sourceVideoSupport({ type: "image/png" }, () => "probably"), { accepted: false, reason: "not-video" });
const zipBytes = new Uint8Array(await buildStoreZip({ "video-v1/README.md": "ready", "video-v1/module.js": "export {};" }).arrayBuffer());
assert.deepEqual([...zipBytes.subarray(0, 4)], [0x50, 0x4b, 0x03, 0x04]);
assert.match(new TextDecoder().decode(zipBytes), /video-v1\/README\.md/);
assert.match(new TextDecoder().decode(zipBytes), /video-v1\/module\.js/);
const plan = bitratePlan(20, true);
assert.ok(plan.videoBitsPerSecond >= 700_000 && plan.videoBitsPerSecond <= 1_000_000);
assert.ok(plan.audioBitsPerSecond >= 48_000 && plan.audioBitsPerSecond <= 64_000);

assert.equal(validateOutput({
  bytes: VIDEO_V1_LIMITS.outputBytes, duration: 20, width: 1280, height: 720, fps: 30,
  videoTracks: 1, audioTracks: 1, mimeType: "video/webm;codecs=av01,opus", posterType: "image/avif",
}).valid, true);
assert.equal(validateOutput({
  bytes: 1000, duration: 0.8, width: 720, height: 720, fps: 30,
  videoTracks: 1, audioTracks: 0, mimeType: "video/webm;codecs=av01", posterType: "image/avif",
}).valid, true, "a one-second editor selection may have slightly shorter encoded container timing");
assert.deepEqual(validateOutput({
  bytes: VIDEO_V1_LIMITS.outputBytes + 1, duration: 21, width: 1282, height: 720, fps: 31,
  videoTracks: 2, audioTracks: 2, mimeType: "video/mp4", posterType: "image/png",
}).failures, ["duration", "size", "fps", "dimensions", "tracks", "codec", "audio-codec", "poster"]);

const entry = await fs.readFile(new URL("./video-v1.entry.js", import.meta.url), "utf8");
const html = await fs.readFile(new URL("./video-v1.html", import.meta.url), "utf8");
const styles = await fs.readFile(new URL("./video-v1.css", import.meta.url), "utf8");
const artifact = JSON.parse(await fs.readFile(new URL("./artifact.json", import.meta.url), "utf8"));
const registry = await fs.readFile(new URL("../app-registry.js", import.meta.url), "utf8");
assert.match(entry, /MediaRecorder/);
assert.match(entry, /captureStream\(VIDEO_V1_LIMITS\.fps\)/);
assert.match(entry, /video\.addEventListener\("timeupdate", watchMediaTime\)/);
assert.match(entry, /setTimeout\(finish, \(range\.duration \+ 2\) \* 1_000\)/);
assert.match(entry, /transcodeToAvif/);
assert.match(entry, /video-v1-complete/);
assert.match(entry, /buildFilmstrip/);
assert.match(entry, /selection\.style\.left/);
assert.match(entry, /leftShade\.style\.width/);
assert.match(entry, /rightShade\.style\.width/);
assert.match(entry, /const moveInterval = \(nextStart\)/);
assert.match(entry, /selection\.setPointerCapture/);
assert.match(entry, /video\.duration - selected\.duration/);
assert.match(entry, /VIDEO_V1_LIMITS\.minDurationSec/);
assert.match(entry, /const watchSelectedRange/);
assert.match(entry, /video\.currentTime = selected\.start/);
assert.match(entry, /playerSeek\.min = String\(selected\.start\)/);
assert.match(entry, /playerSeek\.max = String\(selected\.end\)/);
assert.match(entry, /video\.addEventListener\("timeupdate"/);
assert.match(entry, /video-v1\.css\?v=3/);
assert.match(entry, /resolvedOutputDuration\(media\.duration, selected\.duration\)/);
assert.match(entry, /sourceVideoSupport/);
assert.match(entry, /generation !== importGeneration \|\| destroyed/);
assert.match(entry, /sourceInput\.disabled = true/);
assert.match(entry, /hermes\.wasm_agent\.teaching_module\.v1/);
assert.match(entry, /video-v1-module\.zip/);
assert.match(entry, /buildStoreZip/);
assert.match(entry, /video-v1-module-kit/);
assert.match(entry, /root\.className = "video-v1-mount"/);
assert.match(entry, /const completed = once\(video, "seeked", 8_000\);[\s\S]*video\.currentTime = time;[\s\S]*await completed/);
assert.match(entry, /Media \$\{event\} timed out/);
assert.match(entry, /const metadataReady = once\(video, "loadedmetadata"\);[\s\S]*video\.src = sourceUrl;[\s\S]*await metadataReady/);
assert.match(entry, /async function resolveFiniteMediaDuration/);
assert.match(entry, /\[10_000_000_000, Number\.MAX_SAFE_INTEGER\]/);
assert.match(entry, /Number\.MAX_SAFE_INTEGER/);
assert.match(entry, /once\(video, "durationchange", 8_000\)/);
assert.match(entry, /await metadataReady;[\s\S]*await resolveFiniteMediaDuration\(video\)/);
assert.match(html, /data-filmstrip/);
assert.match(html, /data-shade-left/);
assert.match(html, /data-shade-right/);
assert.match(html, /data-player-seek/);
assert.match(html, /data-download-module/);
assert.match(html, /Download module folder \(\.zip\)/);
assert.match(html, /accept="video\/\*,\.mp4,\.m4v,\.webm,\.mov,\.ogv"/);
assert.match(styles, /\.video-v1-mount>\.vv-shell\{[^}]*overflow-y:auto/);
assert.match(styles, /overscroll-behavior:contain/);
assert.match(styles, /\.video-v1-widget\{display:flex!important;flex-direction:column\}/);
assert.match(styles, /\.video-v1-widget>\.external-app-widget-body\{flex:1 1 0;height:0\}/);
assert.match(html, /class="vv-timeline"[\s\S]*data-start[\s\S]*data-end/);
assert.equal(artifact.videoCodec, "av1");
assert.equal(artifact.poster, "avif");
assert.equal(artifact.limits.outputBytes, 3 * 1024 * 1024);
assert.match(registry, /id: "video-v1"/);
assert.match(registry, /"anaminese", "video-v1"/);

console.log("video-v1 contract tests passed");
