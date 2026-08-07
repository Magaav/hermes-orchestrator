import { bitratePlan, encodedDimensions, normalizeRange, resolvedOutputDuration, sourceVideoSupport, validateOutput, VIDEO_V1_LIMITS } from "./media-contract.js?v=2";
import { transcodeToAvif } from "../batch-cleaner/modules/avif-transcoder.js";
import { buildStoreZip } from "./zip-store.js";

const MIME_WITH_AUDIO = "video/webm;codecs=av01,opus";
const MIME_VIDEO_ONLY = "video/webm;codecs=av01";
let active;

const loadText = async (path) => {
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error(`Video V1 asset failed: ${path}`);
  return response.text();
};

function ensureStylesheet() {
  if (document.querySelector("link[data-video-v1]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./video-v1.css?v=3", import.meta.url).href;
  link.dataset.videoV1 = "";
  document.head.append(link);
}

const once = (target, event, timeoutMs = 30_000) => new Promise((resolve, reject) => {
  let timer;
  const cleanup = () => {
    clearTimeout(timer);
    target.removeEventListener(event, succeeded);
    target.removeEventListener("error", failed);
  };
  const succeeded = (value) => {
    cleanup();
    resolve(value);
  };
  const failed = () => {
    cleanup();
    reject(target.error || new Error(`Media ${event} failed.`));
  };
  target.addEventListener(event, succeeded, { once: true });
  target.addEventListener("error", failed, { once: true });
  timer = setTimeout(() => {
    cleanup();
    reject(new Error(`Media ${event} timed out.`));
  }, timeoutMs);
});

const seek = async (video, time) => {
  if (Math.abs(video.currentTime - time) < 0.01) return;
  const completed = once(video, "seeked", 8_000);
  video.currentTime = time;
  await completed;
};

async function resolveFiniteMediaDuration(video) {
  if (Number.isFinite(video.duration) && video.duration > 0) return video.duration;
  if (video.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) await once(video, "loadeddata", 8_000);
  for (const endpoint of [10_000_000_000, Number.MAX_SAFE_INTEGER]) {
    const endpointReached = Promise.race([
      once(video, "durationchange", 8_000),
      once(video, "seeked", 8_000),
    ]);
    video.currentTime = endpoint;
    await endpointReached;
    const duration = Number.isFinite(video.duration) && video.duration > 0
      ? video.duration
      : video.currentTime;
    if (Number.isFinite(duration) && duration > 0) {
      await seek(video, 0);
      return duration;
    }
  }
  throw new Error("Video duration is unavailable.");
}

const clock = (seconds) => {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds - minutes * 60).toFixed(1).padStart(4, "0")}`;
};

async function buildFilmstrip(video, host, count = 8) {
  const thumbnail = document.createElement("canvas");
  const width = 120;
  const height = Math.max(54, Math.round(width * video.videoHeight / video.videoWidth));
  thumbnail.width = width;
  thumbnail.height = height;
  const context = thumbnail.getContext("2d", { alpha: false });
  const fragment = document.createDocumentFragment();
  for (let index = 0; index < count; index += 1) {
    const time = Math.min(video.duration - 0.01, ((index + 0.5) / count) * video.duration);
    await seek(video, Math.max(0, time));
    context.drawImage(video, 0, 0, width, height);
    const image = document.createElement("img");
    image.alt = "";
    image.src = thumbnail.toDataURL("image/jpeg", 0.62);
    fragment.append(image);
  }
  host.replaceChildren(fragment);
  await seek(video, 0);
}

const canvasBlob = (canvas, type = "image/png") => new Promise((resolve, reject) => {
  canvas.toBlob((blob) => blob ? resolve(blob) : reject(new Error("Poster frame could not be captured.")), type);
});

async function inspectEncodedMedia(blob) {
  const probe = document.createElement("video");
  const url = URL.createObjectURL(blob);
  probe.preload = "metadata";
  probe.src = url;
  try {
    await once(probe, "loadedmetadata");
    return { duration: probe.duration, width: probe.videoWidth, height: probe.videoHeight };
  } finally {
    probe.removeAttribute("src");
    probe.load();
    URL.revokeObjectURL(url);
  }
}

function download(name, blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1_000);
}

async function buildAgentModuleKit() {
  const paths = [
    "artifact.json",
    "media-contract.js",
    "module.js",
    "video-v1.css",
    "video-v1.entry.js",
    "video-v1.html",
    "video-v1.test.mjs",
    "zip-store.js",
  ];
  const files = Object.fromEntries(await Promise.all(paths.map(async (path) => [path, await loadText(`./${path}`)])));
  return {
    schema: "hermes.wasm_agent.teaching_module.v1",
    id: "video-v1",
    version: 14,
    purpose: "Build a browser-local range editor that normalizes compatible video inputs to bounded WebM AV1/Opus plus an AVIF poster.",
    constraints: JSON.parse(files["artifact.json"]),
    architecture: [
      "Keep selected media in ephemeral browser memory and never upload it.",
      "Use one native HTMLVideoElement decode path for preview, thumbnails, and real-time canvas capture.",
      "Keep range, sizing, bitrate, and output validation rules in media-contract.js.",
      "Use the existing single-thread AVIF WASM encoder for the poster.",
      "Prefer verified full-file pass-through when byte-level inspection proves the input already satisfies the output contract.",
    ],
    integration: {
      registry: { id: "video-v1", label: "Video V1", icon: "▶", module: "video-v1", entry: "/modules/video-v1/video-v1.entry.js", minWidth: 320, minHeight: 360 },
      userSpaceMapping: "Add video-v1 to the user Space application mapping.",
      lifecycle: "The entry module exports mount(context) and returns close/destroy/inspect operations.",
    },
    verify: ["node public/modules/video-v1/video-v1.test.mjs", "Run a real browser export and inspect the downloaded WebM with ffprobe."],
    files,
  };
}

function supportedMime(hasAudio) {
  const candidates = hasAudio ? [MIME_WITH_AUDIO] : [MIME_VIDEO_ONLY];
  return candidates.find((value) => globalThis.MediaRecorder?.isTypeSupported?.(value)) || "";
}

async function recordRange({ video, canvas, range, dimensions, status, progress }) {
  const context = canvas.getContext("2d", { alpha: false, colorSpace: "srgb" });
  canvas.width = dimensions.width;
  canvas.height = dimensions.height;
  await seek(video, range.start);
  context.drawImage(video, 0, 0, canvas.width, canvas.height);

  const sourceStream = video.captureStream?.() || video.mozCaptureStream?.();
  const audioTrack = sourceStream?.getAudioTracks?.()[0] || null;
  const mimeType = supportedMime(Boolean(audioTrack));
  if (!mimeType) throw new Error("This browser cannot encode WebM AV1/Opus. Update the native app or use a Chromium build with AV1 MediaRecorder support.");

  const outputStream = canvas.captureStream(VIDEO_V1_LIMITS.fps);
  if (audioTrack) outputStream.addTrack(audioTrack);
  const bitrates = bitratePlan(range.duration, Boolean(audioTrack));
  const recorderOptions = { mimeType, videoBitsPerSecond: bitrates.videoBitsPerSecond };
  if (audioTrack) recorderOptions.audioBitsPerSecond = bitrates.audioBitsPerSecond;
  const recorder = new MediaRecorder(outputStream, recorderOptions);
  const chunks = [];
  recorder.addEventListener("dataavailable", (event) => event.data.size && chunks.push(event.data));
  const stopped = once(recorder, "stop");
  recorder.start(250);
  video.muted = false;
  video.playbackRate = 1;

  let drawing = true;
  const finish = () => {
    if (!drawing) return;
    drawing = false;
    video.pause();
    if (recorder.state !== "inactive") recorder.stop();
  };
  const watchMediaTime = () => {
    if (video.currentTime >= range.end || video.ended) finish();
  };
  const draw = () => {
    if (!drawing) return;
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    progress.value = Math.min(1, Math.max(0, (video.currentTime - range.start) / range.duration));
    if (video.currentTime >= range.end || video.ended) return finish();
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(draw);
    else requestAnimationFrame(draw);
  };
  video.addEventListener("timeupdate", watchMediaTime);
  const watchdog = setTimeout(finish, (range.duration + 2) * 1_000);
  if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(draw);
  else requestAnimationFrame(draw);
  status("Encoding locally in real time…");
  await video.play();
  await stopped;
  drawing = false;
  clearTimeout(watchdog);
  video.removeEventListener("timeupdate", watchMediaTime);
  outputStream.getTracks().forEach((track) => track.stop());
  sourceStream?.getVideoTracks?.().forEach((track) => track.stop());
  return { blob: new Blob(chunks, { type: recorder.mimeType }), mimeType: recorder.mimeType, audioTracks: audioTrack ? 1 : 0 };
}

export async function mount(context = {}) {
  if (active?.root?.isConnected) return active.api;
  ensureStylesheet();
  const mountRoot = context.mountRoot || document.body;
  const root = document.createElement("section");
  root.className = "video-v1-mount";
  root.innerHTML = await loadText("./video-v1.html");
  context.host?.classList.add("video-v1-widget");
  mountRoot.append(root);

  const video = root.querySelector("[data-video]");
  const canvas = root.querySelector("[data-canvas]");
  const sourceInput = root.querySelector("[data-source]");
  const startInput = root.querySelector("[data-start]");
  const endInput = root.querySelector("[data-end]");
  const timeline = root.querySelector("[data-timeline]");
  const selection = root.querySelector("[data-selection]");
  const leftShade = root.querySelector("[data-shade-left]");
  const rightShade = root.querySelector("[data-shade-right]");
  const filmstrip = root.querySelector("[data-filmstrip]");
  const previewButton = root.querySelector("[data-preview]");
  const exportButton = root.querySelector("[data-export]");
  const downloadModuleButton = root.querySelector("[data-download-module]");
  const playerToggle = root.querySelector("[data-player-toggle]");
  const playerSeek = root.querySelector("[data-player-seek]");
  const playerCurrent = root.querySelector("[data-player-current]");
  const playerEnd = root.querySelector("[data-player-end]");
  const progressBox = root.querySelector("[data-progress]");
  const progress = progressBox.querySelector("progress");
  const resultBox = root.querySelector("[data-result]");
  const posterImage = root.querySelector("[data-poster]");
  let sourceUrl = "";
  let posterUrl = "";
  let result = null;
  let busy = false;
  let importGeneration = 0;
  let destroyed = false;

  const setStatus = (message, error = false) => {
    const target = root.querySelector("[data-status]");
    target.textContent = message;
    target.toggleAttribute("data-error", error);
  };

  const range = () => normalizeRange(startInput.value, endInput.value, video.duration);
  const renderRange = (changed) => {
    if (changed === "start" && Number(startInput.value) > Number(endInput.value) - VIDEO_V1_LIMITS.minDurationSec) {
      startInput.value = String(Math.max(0, Number(endInput.value) - VIDEO_V1_LIMITS.minDurationSec));
    }
    if (changed === "start" && Number(endInput.value) > Number(startInput.value) + VIDEO_V1_LIMITS.durationSec) {
      endInput.value = String(Number(startInput.value) + VIDEO_V1_LIMITS.durationSec);
    }
    if (changed === "end" && Number(endInput.value) < Number(startInput.value) + VIDEO_V1_LIMITS.minDurationSec) {
      endInput.value = String(Math.min(video.duration, Number(startInput.value) + VIDEO_V1_LIMITS.minDurationSec));
    }
    if (changed === "end" && Number(endInput.value) > Number(startInput.value) + VIDEO_V1_LIMITS.durationSec) {
      startInput.value = String(Number(endInput.value) - VIDEO_V1_LIMITS.durationSec);
    }
    const selected = range();
    startInput.value = String(selected.start);
    endInput.value = String(selected.end);
    root.querySelector("[data-start-label]").textContent = clock(selected.start);
    root.querySelector("[data-end-label]").textContent = clock(selected.end);
    root.querySelector("[data-duration]").textContent = `${selected.duration.toFixed(1)} s`;
    playerSeek.min = String(selected.start);
    playerSeek.max = String(selected.end);
    playerSeek.value = String(selected.start);
    playerCurrent.textContent = clock(selected.start);
    playerEnd.textContent = clock(selected.end);
    const sourceDuration = Math.max(video.duration || 0, 0.001);
    const leftPercent = (selected.start / sourceDuration) * 100;
    const rightPercent = 100 - (selected.end / sourceDuration) * 100;
    selection.style.left = `${leftPercent}%`;
    selection.style.right = `${rightPercent}%`;
    leftShade.style.width = `${leftPercent}%`;
    rightShade.style.width = `${rightPercent}%`;
    selection.setAttribute("aria-valuemax", String(Math.max(0, sourceDuration - selected.duration)));
    selection.setAttribute("aria-valuenow", String(selected.start));
    selection.setAttribute("aria-valuetext", `${clock(selected.start)} to ${clock(selected.end)}`);
    if (changed && !busy) {
      video.pause();
      video.currentTime = selected.start;
    }
    const invalidDuration = selected.duration < VIDEO_V1_LIMITS.minDurationSec;
    previewButton.disabled = busy || invalidDuration;
    exportButton.disabled = busy || invalidDuration;
    if (changed) {
      resultBox.hidden = true;
      result = null;
    }
  };

  sourceInput.addEventListener("change", async () => {
    const file = sourceInput.files?.[0];
    if (!file) return;
    const generation = ++importGeneration;
    result = null;
    resultBox.hidden = true;
    exportButton.disabled = previewButton.disabled = true;
    const support = sourceVideoSupport(file, (type) => video.canPlayType(type));
    if (!support.accepted) return setStatus(`This browser cannot decode ${file.type || "that video format"}.`, true);
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    sourceUrl = URL.createObjectURL(file);
    const metadataReady = once(video, "loadedmetadata");
    video.src = sourceUrl;
    setStatus("Reading local video metadata…");
    try {
      await metadataReady;
      if (generation !== importGeneration || destroyed) return;
      await resolveFiniteMediaDuration(video);
      const end = Math.min(video.duration, VIDEO_V1_LIMITS.durationSec);
      startInput.max = endInput.max = String(video.duration);
      startInput.value = "0";
      endInput.value = String(end);
      root.querySelector("[data-stage]").hidden = false;
      root.querySelector("[data-trim]").hidden = false;
      root.querySelector("[data-source-duration]").textContent = clock(video.duration);
      renderRange();
      const dimensions = encodedDimensions(video.videoWidth, video.videoHeight);
      setStatus("Building the visual timeline…");
      await buildFilmstrip(video, filmstrip);
      if (generation !== importGeneration || destroyed) return;
      setStatus(`${file.name} ready · ${dimensions.width}×${dimensions.height} output`);
    } catch (error) {
      setStatus(`Could not decode this video: ${error.message}`, true);
    }
  });

  startInput.addEventListener("input", () => renderRange("start"));
  endInput.addEventListener("input", () => renderRange("end"));
  let playbackWatch = 0;
  video.addEventListener("play", () => {
    playerToggle.textContent = "❚❚";
    playerToggle.setAttribute("aria-label", "Pause selected range");
    const token = ++playbackWatch;
    const watchSelectedRange = () => {
      if (token !== playbackWatch || video.paused || busy) return;
      const selected = range();
      if (video.currentTime < selected.start - 0.05 || video.currentTime >= selected.end) {
        video.pause();
        video.currentTime = selected.start;
        return;
      }
      if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(watchSelectedRange);
      else requestAnimationFrame(watchSelectedRange);
    };
    const selected = range();
    if (video.currentTime < selected.start || video.currentTime >= selected.end) video.currentTime = selected.start;
    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(watchSelectedRange);
    else requestAnimationFrame(watchSelectedRange);
  });
  video.addEventListener("pause", () => {
    playbackWatch += 1;
    playerToggle.textContent = "▶";
    playerToggle.setAttribute("aria-label", "Play selected range");
  });
  video.addEventListener("timeupdate", () => {
    const selected = range();
    const boundedTime = Math.min(Math.max(video.currentTime, selected.start), selected.end);
    playerSeek.value = String(boundedTime);
    playerCurrent.textContent = clock(boundedTime);
  });
  playerToggle.addEventListener("click", async () => {
    if (video.paused) await video.play();
    else video.pause();
  });
  playerSeek.addEventListener("input", () => {
    video.currentTime = Number(playerSeek.value);
    playerCurrent.textContent = clock(Number(playerSeek.value));
  });
  downloadModuleButton.addEventListener("click", async () => {
    downloadModuleButton.disabled = true;
    setStatus("Packaging the agent-readable module kit…");
    try {
      const kit = await buildAgentModuleKit();
      const teaching = { ...kit };
      delete teaching.files;
      const readme = `# Video V1 agent module\n\nThis folder is a portable teaching kit for the wasm-agent Video V1 widget.\n\n## Build\n\nCopy the folder under public/modules/video-v1, register the descriptor from TEACHING.json, and run:\n\n    node video-v1.test.mjs\n\nThe widget keeps source media in browser memory and outputs WebM AV1/Opus plus an AVIF poster.\n`;
      const folder = Object.fromEntries(Object.entries(kit.files).map(([path, value]) => [`video-v1/${path}`, value]));
      folder["video-v1/README.md"] = readme;
      folder["video-v1/TEACHING.json"] = `${JSON.stringify(teaching, null, 2)}\n`;
      download("video-v1-module.zip", buildStoreZip(folder));
      setStatus("Module folder downloaded as ZIP. It contains separate source files and no media.");
      root.dispatchEvent(new CustomEvent("video-v1-module-kit", { detail: { schema: kit.schema, files: Object.keys(folder).length, format: "zip" } }));
    } catch (error) {
      setStatus(`Module kit failed: ${error.message}`, true);
    } finally {
      downloadModuleButton.disabled = false;
    }
  });
  const moveInterval = (nextStart) => {
    const selected = range();
    const boundedStart = Math.min(Math.max(0, nextStart), Math.max(0, video.duration - selected.duration));
    startInput.value = String(boundedStart);
    endInput.value = String(boundedStart + selected.duration);
    renderRange("window");
  };
  let intervalDrag = null;
  selection.addEventListener("pointerdown", (event) => {
    if (busy || !sourceUrl) return;
    intervalDrag = { pointerId: event.pointerId, x: event.clientX, start: range().start };
    selection.setPointerCapture(event.pointerId);
    event.preventDefault();
  });
  selection.addEventListener("pointermove", (event) => {
    if (!intervalDrag || intervalDrag.pointerId !== event.pointerId) return;
    const secondsPerPixel = video.duration / Math.max(1, timeline.getBoundingClientRect().width);
    moveInterval(intervalDrag.start + (event.clientX - intervalDrag.x) * secondsPerPixel);
  });
  const finishIntervalDrag = (event) => {
    if (intervalDrag?.pointerId !== event.pointerId) return;
    intervalDrag = null;
    selection.releasePointerCapture?.(event.pointerId);
  };
  selection.addEventListener("pointerup", finishIntervalDrag);
  selection.addEventListener("pointercancel", finishIntervalDrag);
  selection.addEventListener("keydown", (event) => {
    if (!sourceUrl || !["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    moveInterval(range().start + (event.key === "ArrowLeft" ? -1 : 1) * (event.shiftKey ? 1 : 0.25));
    event.preventDefault();
  });
  previewButton.addEventListener("click", async () => {
    const selected = range();
    await seek(video, selected.start);
    video.muted = false;
    await video.play();
  });

  exportButton.addEventListener("click", async () => {
    if (busy) return;
    busy = true;
    sourceInput.disabled = true;
    startInput.disabled = true;
    endInput.disabled = true;
    renderRange();
    exportButton.disabled = previewButton.disabled = true;
    progress.value = 0;
    progressBox.hidden = false;
    resultBox.hidden = true;
    try {
      const selected = range();
      const dimensions = encodedDimensions(video.videoWidth, video.videoHeight);
      await seek(video, selected.start);
      canvas.width = dimensions.width;
      canvas.height = dimensions.height;
      canvas.getContext("2d", { alpha: false }).drawImage(video, 0, 0, canvas.width, canvas.height);
      setStatus("Generating AVIF poster locally…");
      const posterSource = await canvasBlob(canvas);
      const poster = (await transcodeToAvif(posterSource, { quality: 78, speed: 8 })).blob;
      const encoded = await recordRange({ video, canvas, range: selected, dimensions, status: setStatus, progress });
      const media = await inspectEncodedMedia(encoded.blob);
      const outputDuration = resolvedOutputDuration(media.duration, selected.duration);
      const validation = validateOutput({
        bytes: encoded.blob.size, duration: outputDuration, width: media.width, height: media.height, fps: VIDEO_V1_LIMITS.fps,
        videoTracks: 1, audioTracks: encoded.audioTracks, mimeType: encoded.mimeType, posterType: poster.type,
      });
      if (!validation.valid) throw new Error(`Output rejected by: ${validation.failures.join(", ")}.`);
      result = { video: encoded.blob, poster, selected: { ...selected, duration: outputDuration }, dimensions: { width: media.width, height: media.height }, audioTracks: encoded.audioTracks };
      if (posterUrl) URL.revokeObjectURL(posterUrl);
      posterUrl = URL.createObjectURL(poster);
      posterImage.src = posterUrl;
      root.querySelector("[data-result-detail]").textContent = `${media.width}×${media.height} · ${outputDuration.toFixed(1)} s · ${(encoded.blob.size / 1048576).toFixed(2)} MB`;
      resultBox.hidden = false;
      setStatus("Module passed the local output gates.");
      root.dispatchEvent(new CustomEvent("video-v1-complete", { detail: { bytes: encoded.blob.size, width: media.width, height: media.height, duration: outputDuration } }));
    } catch (error) {
      setStatus(`Export failed: ${error.message}`, true);
    } finally {
      busy = false;
      if (!destroyed) {
        sourceInput.disabled = false;
        startInput.disabled = false;
        endInput.disabled = false;
      }
      progressBox.hidden = true;
      renderRange();
      if (result) resultBox.hidden = false;
    }
  });

  root.querySelector("[data-download]").addEventListener("click", () => {
    if (!result) return;
    const manifest = {
      schema: "hermes.wasm_agent.video_module.v1", video: "video-v1.webm", poster: "video-v1.avif",
      container: "webm", videoCodec: "av1", audioCodec: result.audioTracks ? "opus" : null,
      duration: result.selected.duration, ...result.dimensions, fpsMax: 30, metadata: "stripped",
    };
    download("video-v1.webm", result.video);
    download("video-v1.avif", result.poster);
    download("video-v1.json", new Blob([`${JSON.stringify(manifest, null, 2)}\n`], { type: "application/json" }));
  });

  const destroy = () => {
    destroyed = true;
    importGeneration += 1;
    video.pause();
    if (sourceUrl) URL.revokeObjectURL(sourceUrl);
    if (posterUrl) URL.revokeObjectURL(posterUrl);
    root.remove();
    context.host?.classList.remove("video-v1-widget");
    active = undefined;
    context.onClose?.();
  };
  const api = { close: destroy, destroy, inspect: () => ({ busy, loaded: Boolean(sourceUrl), resultBytes: result?.video?.size || 0 }) };
  active = { root, api };
  return api;
}
