export const REMOTE_CONTROL_VIEWPORT_FRAME_KIND = "remote-control-frame";
export const REMOTE_CONTROL_VIEWPORT_FRAME_MS = 1200;
export const REMOTE_CONTROL_VIEWPORT_LIVE_FRAME_MS = 260;
export const REMOTE_CONTROL_VIEWPORT_DURABLE_FRAME_MS = 4800;
export const REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES = 1536 * 1024;
export const REMOTE_CONTROL_VIEWPORT_LIVE_MAX_BYTES = 1152 * 1024;
export const REMOTE_CONTROL_VIEWPORT_FRAME_BOOTSTRAP_MAX_BYTES = 14 * 1024;

const REMOTE_CONTROL_VIEWPORT_FRAME_SIZES = [
  { width: 1920, height: 1080 },
  { width: 1600, height: 900 },
  { width: 1280, height: 720 },
  { width: 960, height: 540 },
  { width: 640, height: 360 },
  { width: 480, height: 270 },
  { width: 360, height: 203 },
  { width: 320, height: 180 },
  { width: 240, height: 135 },
  { width: 160, height: 90 },
  { width: 120, height: 68 },
  { width: 96, height: 54 },
];
const REMOTE_CONTROL_VIEWPORT_FRAME_QUALITIES = [0.94, 0.88, 0.8, 0.7, 0.58, 0.46, 0.36, 0.28, 0.2, 0.14, 0.08, 0.05];
const REMOTE_CONTROL_VIEWPORT_FAST_FRAME_QUALITIES = [0.82, 0.74, 0.64, 0.54, 0.44, 0.34, 0.24, 0.16];
const REMOTE_CONTROL_VIEWPORT_CSS_MAX_CHARS = 240 * 1024;
const REMOTE_CONTROL_VIEWPORT_DOM_MAX_ELEMENTS = 460;
const REMOTE_CONTROL_VIEWPORT_DOM_MAX_TEXT_NODES = 220;
const REMOTE_CONTROL_VIEWPORT_DOM_MAX_TEXT_CHARS = 140;
const REMOTE_CONTROL_SECRET_RE = /password|passwd|secret|token|api[_-]?key|credential|authorization/i;
const REMOTE_CONTROL_BLOCKED_INPUT_TYPES = new Set(["password", "file", "hidden"]);
const REMOTE_CONTROL_CSS_URL_RE = /url\(\s*(['"]?)(.*?)\1\s*\)/gi;

let remoteControlPixelStream = null;
let remoteControlPixelVideo = null;
let remoteControlPixelCanvas = null;
let remoteControlPixelCaptureStopHandler = null;
let remoteControlPixelCaptureEndedNotified = false;

function cleanText(value, fallback = "") {
  const text = String(value ?? "").trim();
  return text || fallback;
}

function clamp(value, min, max) {
  const number = Number(value);
  if (!Number.isFinite(number)) return min;
  return Math.max(min, Math.min(max, number));
}

function dataUrlByteLength(dataUrl) {
  const encoded = String(dataUrl || "").split(",", 2)[1] || "";
  return Math.floor((encoded.length * 3) / 4);
}

function canvasExportTainted(error) {
  return error?.name === "SecurityError" || /tainted canvases/i.test(error?.message || "");
}

function xmlText(value = "") {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function snapshotSafeImageUrl(value = "") {
  const text = cleanText(value, "");
  if (/^data:image\/(?:png|jpe?g|webp|gif);base64,/i.test(text)) {
    return text.replace(/["\\\n\r]/g, "");
  }
  return "";
}

function sanitizeCssResourceUrls(css = "") {
  return String(css ?? "").replace(REMOTE_CONTROL_CSS_URL_RE, (match, quote, rawUrl) => {
    const safeUrl = snapshotSafeImageUrl(rawUrl);
    if (!safeUrl) return "none";
    return `url(${quote || "\""}${safeUrl}${quote || "\""})`;
  });
}

function viewportMetrics() {
  const viewport = window.visualViewport;
  const width = Math.max(1, Math.round(viewport?.width || window.innerWidth || document.documentElement.clientWidth || 1));
  const height = Math.max(1, Math.round(viewport?.height || window.innerHeight || document.documentElement.clientHeight || 1));
  const layoutWidth = Math.max(width, Math.round(window.innerWidth || document.documentElement.clientWidth || width));
  const layoutHeight = Math.max(height, Math.round(window.innerHeight || document.documentElement.clientHeight || height));
  return {
    width,
    height,
    layout_width: layoutWidth,
    layout_height: layoutHeight,
    offset_left: Math.max(0, Math.round(viewport?.offsetLeft || 0)),
    offset_top: Math.max(0, Math.round(viewport?.offsetTop || 0)),
    device_pixel_ratio: Number(window.devicePixelRatio || 1),
  };
}

function viewportFrameSizeCandidates(metrics = viewportMetrics(), options = {}) {
  const sourceWidth = Math.max(1, Math.round(metrics.width || 1));
  const sourceHeight = Math.max(1, Math.round(metrics.height || 1));
  const portrait = sourceHeight > sourceWidth;
  const seen = new Set();
  const sizes = options.fast
    ? REMOTE_CONTROL_VIEWPORT_FRAME_SIZES.filter((size) => Math.max(size.width, size.height) <= 1600)
    : REMOTE_CONTROL_VIEWPORT_FRAME_SIZES;
  return sizes.map((size) => {
    const maxWidth = portrait ? size.height : size.width;
    const maxHeight = portrait ? size.width : size.height;
    const scale = Math.min(1, maxWidth / sourceWidth, maxHeight / sourceHeight);
    return {
      width: Math.max(1, Math.round(sourceWidth * scale)),
      height: Math.max(1, Math.round(sourceHeight * scale)),
    };
  }).filter((size) => {
    const key = `${size.width}x${size.height}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function activePixelCaptureVideo() {
  if (!remoteControlPixelVideo || !remoteControlPixelStream) return null;
  const track = remoteControlPixelStream.getVideoTracks?.()[0];
  if (!track || track.readyState === "ended") {
    stopRemoteControlViewportPixelCapture();
    notifyRemoteControlPixelCaptureStopped("display_capture_ended");
    return null;
  }
  if (remoteControlPixelVideo.readyState < HTMLMediaElement.HAVE_CURRENT_DATA) return null;
  return remoteControlPixelVideo;
}

export function remoteControlViewportPixelCaptureActive() {
  return Boolean(activePixelCaptureVideo());
}

export function setRemoteControlViewportPixelCaptureStopHandler(handler) {
  remoteControlPixelCaptureStopHandler = typeof handler === "function" ? handler : null;
}

function notifyRemoteControlPixelCaptureStopped(reason = "display_capture_ended") {
  if (remoteControlPixelCaptureEndedNotified) return;
  remoteControlPixelCaptureEndedNotified = true;
  try {
    remoteControlPixelCaptureStopHandler?.(reason);
  } catch (error) {
    window.setTimeout(() => { throw error; }, 0);
  }
}

function encodeCanvasFrame(canvas, renderer = "canvas", maxBytes = REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES, options = {}) {
  let lastFrame = null;
  const qualities = options.fast ? REMOTE_CONTROL_VIEWPORT_FAST_FRAME_QUALITIES : REMOTE_CONTROL_VIEWPORT_FRAME_QUALITIES;
  for (const mimeType of ["image/webp", "image/jpeg"]) {
    for (const quality of qualities) {
      const dataUrl = canvas.toDataURL(mimeType, quality);
      if (!dataUrl.startsWith(`data:${mimeType}`)) continue;
      const size = dataUrlByteLength(dataUrl);
      lastFrame = { data_url: dataUrl, width: canvas.width, height: canvas.height, type: mimeType, size, renderer };
      if (size <= maxBytes) return lastFrame;
    }
  }
  return lastFrame;
}

function blobAsDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(reader.error || new Error("Could not read viewport frame."));
    reader.readAsDataURL(blob);
  });
}

function canvasToBlob(canvas, mimeType, quality) {
  return new Promise((resolve) => {
    canvas.toBlob((blob) => resolve(blob), mimeType, quality);
  });
}

async function encodeCanvasFrameAsync(canvas, renderer = "canvas", maxBytes = REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES, options = {}) {
  if (!canvas.toBlob || !window.FileReader) return encodeCanvasFrame(canvas, renderer, maxBytes, options);
  let lastFrame = null;
  const qualities = options.fast ? REMOTE_CONTROL_VIEWPORT_FAST_FRAME_QUALITIES : REMOTE_CONTROL_VIEWPORT_FRAME_QUALITIES;
  for (const mimeType of ["image/webp", "image/jpeg"]) {
    for (const quality of qualities) {
      const blob = await canvasToBlob(canvas, mimeType, quality);
      if (!blob || !blob.type.startsWith(mimeType)) continue;
      const dataUrl = await blobAsDataUrl(blob);
      if (!dataUrl.startsWith(`data:${mimeType}`)) continue;
      const frame = { data_url: dataUrl, width: canvas.width, height: canvas.height, type: mimeType, size: blob.size, renderer };
      lastFrame = frame;
      if (blob.size <= maxBytes) return frame;
    }
  }
  return lastFrame;
}

async function waitForPixelVideoReady(video) {
  if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA && video.videoWidth && video.videoHeight) return;
  await new Promise((resolve, reject) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      resolve();
    };
    const fail = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      reject(new Error("Exact viewport sharing did not start."));
    };
    const timeout = window.setTimeout(fail, 7000);
    video.addEventListener("loadedmetadata", finish, { once: true });
    video.addEventListener("loadeddata", finish, { once: true });
    video.addEventListener("error", fail, { once: true });
  });
}

export async function startRemoteControlViewportPixelCapture() {
  if (activePixelCaptureVideo()) return true;
  if (!navigator.mediaDevices?.getDisplayMedia) return false;
  stopRemoteControlViewportPixelCapture();
  const stream = await navigator.mediaDevices.getDisplayMedia({
    video: {
      width: { ideal: 1920 },
      height: { ideal: 1080 },
      frameRate: { ideal: 5, max: 8 },
      displaySurface: "browser",
    },
    audio: false,
    preferCurrentTab: true,
    selfBrowserSurface: "include",
    surfaceSwitching: "exclude",
  });
  remoteControlPixelCaptureEndedNotified = false;
  const video = document.createElement("video");
  video.muted = true;
  video.playsInline = true;
  video.srcObject = stream;
  const stopOnEnd = () => {
    stopRemoteControlViewportPixelCapture();
    notifyRemoteControlPixelCaptureStopped("display_capture_ended");
  };
  stream.getVideoTracks?.().forEach((track) => track.addEventListener("ended", stopOnEnd, { once: true }));
  remoteControlPixelStream = stream;
  remoteControlPixelVideo = video;
  await video.play?.();
  await waitForPixelVideoReady(video);
  return true;
}

export function stopRemoteControlViewportPixelCapture() {
  const stream = remoteControlPixelStream;
  remoteControlPixelStream = null;
  if (remoteControlPixelVideo) {
    remoteControlPixelVideo.pause?.();
    remoteControlPixelVideo.srcObject = null;
  }
  remoteControlPixelVideo = null;
  remoteControlPixelCanvas = null;
  stream?.getTracks?.().forEach((track) => {
    try {
      track.stop();
    } catch {
      // Track may already be stopped by the browser.
    }
  });
}

async function encodePixelCaptureFrame(metrics = viewportMetrics(), maxBytes = REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES, options = {}) {
  const video = activePixelCaptureVideo();
  if (!video) return null;
  const sourceWidth = Math.max(1, Math.round(video.videoWidth || metrics.width));
  const sourceHeight = Math.max(1, Math.round(video.videoHeight || metrics.height));
  let lastFrame = null;
  for (const size of viewportFrameSizeCandidates({ width: sourceWidth, height: sourceHeight }, options)) {
    const canvas = remoteControlPixelCanvas || document.createElement("canvas");
    remoteControlPixelCanvas = canvas;
    canvas.width = size.width;
    canvas.height = size.height;
    const ctx = canvas.getContext("2d");
    if (!ctx) continue;
    ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
    const frame = await encodeCanvasFrameAsync(canvas, "display-capture", maxBytes, options);
    if (frame) lastFrame = { ...frame, source_width: sourceWidth, source_height: sourceHeight };
    if (frame && frame.size <= maxBytes) return lastFrame;
  }
  if (lastFrame) throw new Error("Viewport frame was too large to relay.");
  return null;
}

function captureCss() {
  let css = "";
  for (const sheet of Array.from(document.styleSheets || [])) {
    try {
      for (const rule of Array.from(sheet.cssRules || [])) {
        if (css.length >= REMOTE_CONTROL_VIEWPORT_CSS_MAX_CHARS) break;
        css += `${sanitizeCssResourceUrls(rule.cssText)}\n`;
      }
    } catch {
      // Cross-origin and transient stylesheets are fine to omit.
    }
    if (css.length >= REMOTE_CONTROL_VIEWPORT_CSS_MAX_CHARS) break;
  }
  return css.slice(0, REMOTE_CONTROL_VIEWPORT_CSS_MAX_CHARS);
}

function sensitiveField(element) {
  const type = cleanText(element?.getAttribute?.("type") || "").toLowerCase();
  const nameBits = [
    element?.id,
    element?.getAttribute?.("name"),
    element?.getAttribute?.("autocomplete"),
    element?.getAttribute?.("placeholder"),
    element?.getAttribute?.("aria-label"),
  ].join(" ");
  return REMOTE_CONTROL_BLOCKED_INPUT_TYPES.has(type) || REMOTE_CONTROL_SECRET_RE.test(nameBits);
}

function replaceSnapshotMedia(element) {
  const replacement = document.createElement("div");
  const rect = element.getBoundingClientRect?.() || {};
  const width = Math.max(1, Math.round(Number(rect.width || element.width || element.clientWidth || 160)));
  const height = Math.max(1, Math.round(Number(rect.height || element.height || element.clientHeight || 96)));
  replacement.className = "remote-control-media-placeholder";
  replacement.textContent = element.tagName?.toLowerCase?.() || "media";
  replacement.setAttribute("aria-hidden", "true");
  replacement.style.cssText = [
    `width:${width}px`,
    `height:${height}px`,
    "display:flex",
    "align-items:center",
    "justify-content:center",
    "background:#0b1320",
    "color:#8ea2bd",
    "border:1px solid rgba(147,170,203,.24)",
    "border-radius:6px",
    "font:12px system-ui,sans-serif",
    "box-sizing:border-box",
  ].join(";");
  element.replaceWith(replacement);
}

function sanitizeSnapshotClone(clone) {
  clone.querySelectorAll?.("[data-remote-control], script, iframe").forEach((node) => node.remove());
  clone.querySelectorAll?.("[style]").forEach((element) => {
    const style = sanitizeCssResourceUrls(element.getAttribute("style") || "");
    if (style.trim()) element.setAttribute("style", style);
    else element.removeAttribute("style");
  });
  clone.querySelectorAll?.("input").forEach((input) => {
    if (sensitiveField(input)) {
      input.setAttribute("value", "");
      input.setAttribute("placeholder", "[redacted]");
      return;
    }
    if (input.checked) input.setAttribute("checked", "checked");
    else input.removeAttribute("checked");
    input.setAttribute("value", input.value || "");
  });
  clone.querySelectorAll?.("textarea").forEach((textarea) => {
    if (sensitiveField(textarea)) {
      textarea.textContent = "";
      textarea.setAttribute("placeholder", "[redacted]");
    } else {
      textarea.textContent = textarea.value || "";
    }
  });
  clone.querySelectorAll?.("select").forEach((select) => {
    Array.from(select.options || []).forEach((option) => {
      if (option.selected) option.setAttribute("selected", "selected");
      else option.removeAttribute("selected");
    });
  });
  clone.querySelectorAll?.("canvas, video, iframe").forEach(replaceSnapshotMedia);
  clone.querySelectorAll?.("img").forEach((image) => {
    const src = cleanText(image.getAttribute("src") || "");
    if (!snapshotSafeImageUrl(src)) {
      replaceSnapshotMedia(image);
    }
  });
}

function viewportSvg(metrics = viewportMetrics()) {
  const source = document.querySelector("#app") || document.body;
  if (!source) return "";
  const clone = source.cloneNode(true);
  sanitizeSnapshotClone(clone);
  clone.setAttribute("xmlns", "http://www.w3.org/1999/xhtml");
  clone.style.width = `${metrics.layout_width}px`;
  clone.style.minHeight = `${metrics.layout_height}px`;
  clone.style.margin = "0";
  const html = new XMLSerializer().serializeToString(clone);
  const css = `${captureCss()}
html,body{margin:0!important;background:#08101c!important;overflow:hidden!important;}
*{box-sizing:border-box!important;caret-color:transparent!important;}
.remote-control-media-placeholder{letter-spacing:0!important;text-transform:none!important;}`;
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" width="${metrics.width}" height="${metrics.height}" viewBox="0 0 ${metrics.width} ${metrics.height}">`,
    `<foreignObject x="0" y="0" width="${metrics.width}" height="${metrics.height}">`,
    `<div xmlns="http://www.w3.org/1999/xhtml" style="position:relative;width:${metrics.width}px;height:${metrics.height}px;overflow:hidden;background:#08101c;">`,
    `<style>${xmlText(css)}</style>`,
    `<div style="position:absolute;left:${-metrics.offset_left}px;top:${-metrics.offset_top}px;width:${metrics.layout_width}px;min-height:${metrics.layout_height}px;">`,
    html,
    "</div></div></foreignObject></svg>",
  ].join("");
}

function loadImageSource(src, label = "viewport frame") {
  return new Promise((resolve, reject) => {
    const image = new Image();
    let settled = false;
    const timeout = window.setTimeout(() => {
      if (settled) return;
      settled = true;
      reject(new Error(`${label} timed out`));
    }, 2500);
    image.onload = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      resolve(image);
    };
    image.onerror = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      reject(new Error(`Could not render ${label}`));
    };
    image.src = src;
  });
}

function visibleCssColor(value = "") {
  const color = cleanText(value, "").toLowerCase();
  return color && color !== "transparent" && !/rgba?\([^)]+,\s*0(?:\.0+)?\)$/i.test(color);
}

function cssPixels(value, fallback = 0) {
  const number = Number.parseFloat(value);
  return Number.isFinite(number) ? number : fallback;
}

function viewportIntersection(rect, metrics) {
  const left = clamp(rect.left, 0, metrics.width);
  const top = clamp(rect.top, 0, metrics.height);
  const right = clamp(rect.right, 0, metrics.width);
  const bottom = clamp(rect.bottom, 0, metrics.height);
  if (right - left < 1 || bottom - top < 1) return null;
  return { left, top, right, bottom, width: right - left, height: bottom - top };
}

function frameRect(rect, scaleX, scaleY) {
  return {
    x: rect.left * scaleX,
    y: rect.top * scaleY,
    width: Math.max(1, rect.width * scaleX),
    height: Math.max(1, rect.height * scaleY),
  };
}

function elementVisible(element, style = window.getComputedStyle(element)) {
  if (element.closest?.("[data-remote-control]")) return false;
  if (style.display === "none" || style.visibility === "hidden") return false;
  return Number(style.opacity || 1) > 0.02;
}

function canvasFont(style, scale = 1) {
  const fontSize = clamp(cssPixels(style.fontSize, 12), 8, 28) * scale;
  const weight = cleanText(style.fontWeight, "400");
  const italic = style.fontStyle === "italic" ? "italic " : "";
  return `${italic}${weight} ${Math.max(7, fontSize).toFixed(1)}px system-ui, sans-serif`;
}

function drawSnapshotText(ctx, text, rect, style, scaleX, scaleY, options = {}) {
  const clean = cleanText(String(text ?? "").replace(/\s+/g, " "), "");
  if (!clean || rect.width < 4 || rect.height < 4) return;
  const target = frameRect(rect, scaleX, scaleY);
  const fontScale = Math.min(scaleX, scaleY);
  const paddingX = Math.min(target.width * 0.12, (options.paddingX ?? 6) * scaleX);
  const paddingY = Math.min(target.height * 0.22, (options.paddingY ?? 4) * scaleY);
  ctx.save();
  ctx.beginPath();
  ctx.rect(target.x, target.y, target.width, target.height);
  ctx.clip();
  ctx.font = canvasFont(style, fontScale);
  ctx.fillStyle = visibleCssColor(style.color) ? style.color : "#edf5ff";
  ctx.textBaseline = "top";
  ctx.fillText(
    clean.slice(0, REMOTE_CONTROL_VIEWPORT_DOM_MAX_TEXT_CHARS),
    target.x + paddingX,
    target.y + paddingY,
    Math.max(1, target.width - paddingX * 2)
  );
  ctx.restore();
}

function formElementSnapshotText(element) {
  if (element instanceof HTMLInputElement) {
    if (sensitiveField(element)) return "[redacted]";
    if (["checkbox", "radio"].includes(cleanText(element.type, "").toLowerCase())) return element.checked ? "on" : "off";
    return element.value || element.placeholder || "";
  }
  if (element instanceof HTMLTextAreaElement) {
    if (sensitiveField(element)) return "[redacted]";
    return element.value || element.placeholder || "";
  }
  if (element instanceof HTMLSelectElement) {
    return element.selectedOptions?.[0]?.textContent || "";
  }
  return "";
}

function drawElementSnapshot(ctx, element, metrics, scaleX, scaleY) {
  if (!(element instanceof Element)) return false;
  const style = window.getComputedStyle(element);
  if (!elementVisible(element, style)) return false;
  const rect = viewportIntersection(element.getBoundingClientRect(), metrics);
  if (!rect) return false;
  const target = frameRect(rect, scaleX, scaleY);
  const background = style.backgroundColor;
  if (visibleCssColor(background)) {
    ctx.fillStyle = background;
    ctx.fillRect(target.x, target.y, target.width, target.height);
  }
  const borderWidth = Math.max(
    cssPixels(style.borderTopWidth),
    cssPixels(style.borderRightWidth),
    cssPixels(style.borderBottomWidth),
    cssPixels(style.borderLeftWidth)
  );
  if (borderWidth > 0 && visibleCssColor(style.borderTopColor)) {
    ctx.strokeStyle = style.borderTopColor;
    ctx.lineWidth = Math.max(0.5, borderWidth * Math.min(scaleX, scaleY));
    ctx.strokeRect(target.x, target.y, target.width, target.height);
  }
  if (element.matches?.("img,canvas,video,iframe")) {
    ctx.fillStyle = "rgba(11,19,32,.86)";
    ctx.fillRect(target.x, target.y, target.width, target.height);
    ctx.strokeStyle = "rgba(147,170,203,.38)";
    ctx.lineWidth = 1;
    ctx.strokeRect(target.x + 0.5, target.y + 0.5, Math.max(1, target.width - 1), Math.max(1, target.height - 1));
    drawSnapshotText(ctx, element.tagName.toLowerCase(), rect, style, scaleX, scaleY, { paddingX: 8, paddingY: 6 });
  } else if (element.matches?.("input,textarea,select")) {
    drawSnapshotText(ctx, formElementSnapshotText(element), rect, style, scaleX, scaleY);
  }
  return true;
}

function drawTextNodeSnapshot(ctx, textNode, metrics, scaleX, scaleY) {
  const parent = textNode.parentElement;
  if (!parent) return false;
  const style = window.getComputedStyle(parent);
  if (!elementVisible(parent, style)) return false;
  const text = cleanText(textNode.textContent || "", "").replace(/\s+/g, " ");
  if (!text) return false;
  const range = document.createRange();
  try {
    range.selectNodeContents(textNode);
    const rect = Array.from(range.getClientRects()).map((candidate) => viewportIntersection(candidate, metrics)).find(Boolean);
    if (!rect) return false;
    drawSnapshotText(ctx, text, rect, style, scaleX, scaleY, { paddingX: 0, paddingY: 0 });
    return true;
  } finally {
    range.detach?.();
  }
}

function paintViewportDomFrame(canvas, metrics = viewportMetrics()) {
  const ctx = canvas.getContext("2d");
  if (!ctx) return false;
  const scaleX = canvas.width / Math.max(1, metrics.width);
  const scaleY = canvas.height / Math.max(1, metrics.height);
  ctx.fillStyle = "#08101c";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const source = document.querySelector("#app") || document.body;
  if (!source) return true;

  const elements = [source, ...Array.from(source.querySelectorAll?.("*") || [])].slice(0, REMOTE_CONTROL_VIEWPORT_DOM_MAX_ELEMENTS);
  elements.forEach((element) => drawElementSnapshot(ctx, element, metrics, scaleX, scaleY));

  const walker = document.createTreeWalker(source, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      return cleanText(node.textContent || "", "") ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
    },
  });
  let textCount = 0;
  while (textCount < REMOTE_CONTROL_VIEWPORT_DOM_MAX_TEXT_NODES) {
    const node = walker.nextNode();
    if (!node) break;
    if (drawTextNodeSnapshot(ctx, node, metrics, scaleX, scaleY)) textCount += 1;
  }
  return true;
}

function encodeViewportDomFrame(metrics = viewportMetrics(), maxBytes = REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES) {
  let lastFrame = null;
  for (const size of viewportFrameSizeCandidates(metrics)) {
    const outputWidth = size.width;
    const outputHeight = size.height;
    const canvas = document.createElement("canvas");
    canvas.width = outputWidth;
    canvas.height = outputHeight;
    if (!paintViewportDomFrame(canvas, metrics)) continue;
    for (const mimeType of ["image/webp", "image/jpeg"]) {
      for (const quality of REMOTE_CONTROL_VIEWPORT_FRAME_QUALITIES) {
        const dataUrl = canvas.toDataURL(mimeType, quality);
        if (!dataUrl.startsWith(`data:${mimeType}`)) continue;
        const size = dataUrlByteLength(dataUrl);
        lastFrame = { data_url: dataUrl, width: outputWidth, height: outputHeight, type: mimeType, size, renderer: "dom-canvas" };
        if (size <= maxBytes) return lastFrame;
      }
    }
  }
  throw new Error("Viewport frame was too large to relay.");
}

async function encodeViewportFrame(svg, metrics = viewportMetrics(), maxBytes = REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES) {
  if (!svg) throw new Error("Viewport snapshot is empty.");
  const blob = new Blob([svg], { type: "image/svg+xml;charset=utf-8" });
  const objectUrl = URL.createObjectURL(blob);
  try {
    const image = await loadImageSource(objectUrl, "viewport frame");
    let lastFrame = null;
    for (const size of viewportFrameSizeCandidates(metrics)) {
      const outputWidth = size.width;
      const outputHeight = size.height;
      const canvas = document.createElement("canvas");
      canvas.width = outputWidth;
      canvas.height = outputHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) continue;
      ctx.fillStyle = "#08101c";
      ctx.fillRect(0, 0, outputWidth, outputHeight);
      ctx.drawImage(image, 0, 0, outputWidth, outputHeight);
      for (const mimeType of ["image/webp", "image/jpeg"]) {
        for (const quality of REMOTE_CONTROL_VIEWPORT_FRAME_QUALITIES) {
          let dataUrl = "";
          try {
            dataUrl = canvas.toDataURL(mimeType, quality);
          } catch (error) {
            if (canvasExportTainted(error)) throw error;
            continue;
          }
          if (!dataUrl.startsWith(`data:${mimeType}`)) continue;
          const size = dataUrlByteLength(dataUrl);
          lastFrame = { data_url: dataUrl, width: outputWidth, height: outputHeight, type: mimeType, size, renderer: "svg-foreign-object" };
          if (size <= maxBytes) return lastFrame;
        }
      }
    }
    throw new Error("Viewport frame was too large to relay.");
  } finally {
    URL.revokeObjectURL(objectUrl);
  }
}

export async function captureRemoteControlViewportFrame(reason = "timer", options = {}) {
  const metrics = viewportMetrics();
  const maxBytes = clamp(
    options.maxBytes ?? REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES,
    REMOTE_CONTROL_VIEWPORT_FRAME_BOOTSTRAP_MAX_BYTES,
    REMOTE_CONTROL_VIEWPORT_FRAME_DEFAULT_MAX_BYTES
  );
  try {
    const pixelFrame = await encodePixelCaptureFrame(metrics, maxBytes, { fast: Boolean(options.fast) });
    if (pixelFrame) {
      return {
        ...pixelFrame,
        reason,
        viewport_width: metrics.width,
        viewport_height: metrics.height,
        layout_width: metrics.layout_width,
        layout_height: metrics.layout_height,
        device_pixel_ratio: metrics.device_pixel_ratio,
      };
    }
  } catch (error) {
    if (!/too large/i.test(error?.message || "")) throw error;
  }
  const svg = viewportSvg(metrics);
  let encoded = null;
  try {
    encoded = await encodeViewportFrame(svg, metrics, maxBytes);
  } catch (error) {
    try {
      encoded = encodeViewportDomFrame(metrics, maxBytes);
    } catch (fallbackError) {
      if (fallbackError instanceof Error && !canvasExportTainted(error)) {
        fallbackError.message = `${fallbackError.message} after SVG snapshot failed: ${error.message || String(error)}`;
      }
      throw fallbackError;
    }
  }
  return {
    ...encoded,
    reason,
    viewport_width: metrics.width,
    viewport_height: metrics.height,
    layout_width: metrics.layout_width,
    layout_height: metrics.layout_height,
    device_pixel_ratio: metrics.device_pixel_ratio,
  };
}

export function remoteControlViewportPoint(event) {
  const frame = event.currentTarget?.closest?.("[data-remote-control-viewport-frame]")
    || event.target?.closest?.("[data-remote-control-viewport-frame]");
  const rect = frame?.getBoundingClientRect?.();
  if (!rect || rect.width <= 0 || rect.height <= 0) return null;
  const imageWidth = Number(frame.dataset.remoteControlImageWidth || frame.naturalWidth || 0);
  const imageHeight = Number(frame.dataset.remoteControlImageHeight || frame.naturalHeight || 0);
  const imageAspect = imageWidth > 0 && imageHeight > 0 ? imageWidth / imageHeight : rect.width / rect.height;
  const boxAspect = rect.width / rect.height;
  let contentLeft = rect.left;
  let contentTop = rect.top;
  let contentWidth = rect.width;
  let contentHeight = rect.height;
  if (imageAspect > 0 && Number.isFinite(imageAspect)) {
    if (boxAspect > imageAspect) {
      contentHeight = rect.height;
      contentWidth = rect.height * imageAspect;
      contentLeft = rect.left + (rect.width - contentWidth) / 2;
    } else {
      contentWidth = rect.width;
      contentHeight = rect.width / imageAspect;
      contentTop = rect.top + (rect.height - contentHeight) / 2;
    }
  }
  if (
    event.clientX < contentLeft
    || event.clientX > contentLeft + contentWidth
    || event.clientY < contentTop
    || event.clientY > contentTop + contentHeight
  ) {
    return null;
  }
  return {
    x_ratio: clamp((event.clientX - contentLeft) / Math.max(1, contentWidth), 0, 1),
    y_ratio: clamp((event.clientY - contentTop) / Math.max(1, contentHeight), 0, 1),
    viewport_width: Number(frame.dataset.remoteControlViewportWidth || 0),
    viewport_height: Number(frame.dataset.remoteControlViewportHeight || 0),
  };
}

export function removeRemoteControlViewportPanel() {
  document.querySelector("[data-remote-control-viewport]")?.remove();
}

function remoteControlViewportStatusText(controller = {}, frame = null, receivedAt = 0, now = Date.now()) {
  if (frame?.image) {
    const age = Math.max(0, Math.round((now - Number(receivedAt || now)) / 1000));
    const viewport = frame.viewport_width && frame.viewport_height ? `${frame.viewport_width}x${frame.viewport_height}` : "viewport";
    const rendered = frame.width && frame.height ? `${frame.width}x${frame.height}` : "frame";
    const exact = frame.renderer === "display-capture" ? "exact pixels" : "snapshot";
    const bytes = Number(frame.image_bytes || 0);
    const quality = bytes > 0 ? ` / ${Math.round(bytes / 1024)} KiB` : "";
    const message = frame.status && frame.status !== "ok" ? cleanText(frame.message, "") : "";
    return message
      ? `${rendered} / ${viewport} / ${exact}${quality} / ${message}`
      : `${rendered} / ${viewport} / ${exact}${quality} / ${age}s ago`;
  }
  return cleanText(frame?.message, `Requesting ${controller.target_label || "remote"} viewport`);
}

function updateRemoteControlViewportToggle(panel, toggle) {
  const expanded = panel.dataset.expanded === "true";
  panel.classList.toggle("is-expanded", expanded);
  toggle.setAttribute("aria-label", expanded ? "Restore viewport" : "Expand viewport");
  toggle.setAttribute("aria-pressed", expanded ? "true" : "false");
  toggle.title = expanded ? "Restore viewport" : "Expand viewport";
}

function buildRemoteControlViewportPanel(panel) {
  panel.replaceChildren();
  const header = document.createElement("div");
  header.className = "remote-control-viewport-head";
  const title = document.createElement("strong");
  title.dataset.remoteControlViewportTitle = "true";
  const status = document.createElement("span");
  status.dataset.remoteControlViewportStatus = "true";
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "remote-control-viewport-toggle";
  toggle.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    panel.dataset.expanded = panel.dataset.expanded !== "true" ? "true" : "false";
    updateRemoteControlViewportToggle(panel, toggle);
    panel.focus?.({ preventScroll: true });
  });
  header.append(title, status, toggle);

  const body = document.createElement("div");
  body.className = "remote-control-viewport-body";
  body.dataset.remoteControlViewportBody = "true";
  const image = document.createElement("img");
  image.dataset.remoteControlViewportFrame = "true";
  image.decoding = "async";
  image.draggable = false;
  image.hidden = true;
  const placeholder = document.createElement("span");
  placeholder.dataset.remoteControlViewportPlaceholder = "true";
  body.append(image, placeholder);
  panel.append(header, body);
}

function installRemoteControlViewportImageHandlers(image, handlers = {}) {
  if (image.dataset.remoteControlHandlersInstalled === "true") return;
  image.dataset.remoteControlHandlersInstalled = "true";
  if (handlers.onClick) image.addEventListener("click", handlers.onClick);
  if (handlers.onWheel) image.addEventListener("wheel", handlers.onWheel, { passive: false });
  if (handlers.onPointerDown) image.addEventListener("pointerdown", handlers.onPointerDown, { passive: false });
  if (handlers.onPointerMove) image.addEventListener("pointermove", handlers.onPointerMove, { passive: false });
  if (handlers.onPointerUp) {
    image.addEventListener("pointerup", handlers.onPointerUp, { passive: false });
    image.addEventListener("pointercancel", handlers.onPointerUp, { passive: false });
    image.addEventListener("lostpointercapture", handlers.onPointerUp);
  }
}

export function renderRemoteControlViewportPanel({
  controller,
  frame = null,
  receivedAt = 0,
  now = Date.now(),
  onClick,
  onWheel,
  onKeydown,
  onPointerDown,
  onPointerMove,
  onPointerUp,
} = {}) {
  if (!controller) {
    removeRemoteControlViewportPanel();
    return;
  }
  const handlers = { onClick, onWheel, onPointerDown, onPointerMove, onPointerUp };
  let panel = document.querySelector("[data-remote-control-viewport]");
  if (!panel) {
    panel = document.createElement("section");
    panel.className = "remote-control-viewport";
    panel.dataset.remoteControl = "true";
    panel.dataset.remoteControlViewport = "true";
    panel.tabIndex = 0;
    panel.setAttribute("aria-live", "polite");
    if (onKeydown) panel.addEventListener("keydown", onKeydown);
    document.body.append(panel);
  }
  if (!panel.querySelector("[data-remote-control-viewport-body]")) buildRemoteControlViewportPanel(panel);
  const toggle = panel.querySelector(".remote-control-viewport-toggle");
  if (toggle) updateRemoteControlViewportToggle(panel, toggle);
  const title = panel.querySelector("[data-remote-control-viewport-title]");
  const status = panel.querySelector("[data-remote-control-viewport-status]");
  const image = panel.querySelector("[data-remote-control-viewport-frame]");
  const placeholder = panel.querySelector("[data-remote-control-viewport-placeholder]");
  title.textContent = `${controller.target_label || "Remote"} viewport`;
  status.textContent = remoteControlViewportStatusText(controller, frame, receivedAt, now);
  installRemoteControlViewportImageHandlers(image, handlers);
  if (frame?.image) {
    image.alt = `${controller.target_label || "Remote"} viewport`;
    if (image.getAttribute("src") !== frame.image) image.src = frame.image;
    image.dataset.remoteControlImageWidth = String(frame.width || "");
    image.dataset.remoteControlImageHeight = String(frame.height || "");
    image.dataset.remoteControlViewportWidth = String(frame.viewport_width || "");
    image.dataset.remoteControlViewportHeight = String(frame.viewport_height || "");
    image.hidden = false;
    placeholder.hidden = true;
  } else {
    placeholder.textContent = cleanText(frame?.message, "Requesting remote viewport");
    placeholder.hidden = false;
    image.hidden = true;
  }
}
