import {
  findObjects,
  disposeDetector
} from "../property-photo-cleaner/modules/object-detector.js";
import {
  cleanSelectedObjects,
  disposeObjectCleaner
} from "../property-photo-cleaner/modules/local-object-cleaner.js?v=20260727-lama-baseline1";
import {
  reconstructSelectedObjects,
  disposeQualityCleaner
} from "../property-photo-cleaner/modules/moebius-quality-cleaner.js?v=20260727-moebius2";
import { cleanWithCloudQuality } from "./modules/cloud-quality-cleaner.js";
import {
  acceptedBatchFiles,
  batchSummary,
  canCleanBatch,
  cleanableDetections,
  cleanedFilename,
  MAX_BATCH_PHOTOS
} from "./modules/batch-queue.js";
import { createZip, downloadZip } from "./modules/zip-export.js";
import { enhanceReality, disposeRealityEnhancer } from "./modules/reality-enhancer.js";

const ROOT_ID = "batch-cleaner-root";
const WORKING_STATES = new Set([
  "queued-detection",
  "detecting",
  "queued-clean",
  "cleaning",
  "queued-enhance",
  "enhancing"
]);
let active = null;

async function loadText(path) {
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error(`Batch Cleaner asset failed: ${path}`);
  return response.text();
}

function ensureStylesheet() {
  if (document.querySelector("link[data-batch-cleaner]")) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./batch-cleaner.css", import.meta.url).href;
  link.dataset.batchCleaner = "";
  document.head.append(link);
}

async function imageSize(blob) {
  const bitmap = await createImageBitmap(blob);
  const size = { width: bitmap.width, height: bitmap.height };
  bitmap.close();
  return size;
}

export async function mount(context = {}) {
  if (active) {
    active.root.hidden = false;
    return active.api;
  }
  ensureStylesheet();
  const root = document.createElement("section");
  root.id = ROOT_ID;
  root.innerHTML = await loadText("./batch-cleaner.html");
  (context.mountRoot || document.body).appendChild(root);
  if (context.host && !context.host.classList.contains("is-maximized")) {
    context.host.querySelector('[data-widget-control="maximize"]')?.click();
  }

  const items = [];
  const cards = new Map();
  const fileInput = root.querySelector('input[type="file"]');
  const grid = root.querySelector("[data-grid]");
  const dropZone = root.querySelector("[data-drop-zone]");
  const empty = root.querySelector("[data-empty]");
  const summaryLine = root.querySelector("[data-summary]");
  const overallLine = root.querySelector("[data-overall]");
  const statusLine = root.querySelector("[data-status]");
  const errorLine = root.querySelector("[data-error]");
  const preview = root.querySelector("[data-preview]");
  const previewImage = root.querySelector("[data-preview-image]");
  const watermarkAuthorized = root.querySelector("[data-watermark-authorized]");
  const enhanceRealityInput = root.querySelector("[data-enhance-reality]");
  const qualityReconstructionInput = root.querySelector("[data-quality-reconstruction]");
  const cloudQualityInput = root.querySelector("[data-cloud-quality]");
  let detectionRunning = false;
  let cleaningRunning = false;
  let exporting = false;
  let disposed = false;
  let previewItem = null;

  function action(name) {
    return root.querySelector(`[data-action="${name}"]`);
  }

  function itemState(item) {
    if (!item.included) return { label: "Excluded · click + to include", passive: true };
    const labels = {
      "queued-detection": "Queued for object detection",
      detecting: item.detail || "Finding every object…",
      ready: `Ready · ${cleanableDetections(item).length} removable objects`,
      "queued-clean": "Queued for cleaning",
      cleaning: item.detail || "Reconstructing locally…",
      "queued-enhance": "Queued for reality enhancement",
      enhancing: item.detail || "Enhancing reality…",
      cleaned: item.enhanced ? "Enhanced · click to compare" : "Cleaned · click to compare",
      failed: `Failed · ${item.error || "retry by including again"}`
    };
    return { label: labels[item.state] || item.state, passive: ["ready", "cleaned", "failed"].includes(item.state) };
  }

  function updateCard(item) {
    let card = cards.get(item.id);
    if (!card) {
      card = document.createElement("article");
      card.className = "bc-card";
      card.dataset.itemId = item.id;
      const image = document.createElement("img");
      image.alt = item.name;
      const state = document.createElement("div");
      state.className = "bc-card-state";
      const toggle = document.createElement("button");
      toggle.type = "button";
      toggle.className = "bc-card-toggle";
      toggle.dataset.toggleItem = item.id;
      card.append(image, state, toggle);
      card.addEventListener("click", (event) => {
        if (event.target.closest("[data-toggle-item]")) return;
        openPreview(item);
      });
      grid.appendChild(card);
      cards.set(item.id, card);
    }
    card.toggleAttribute("data-excluded", !item.included);
    card.querySelector("img").src = item.cleanedUrl || item.sourceUrl;
    const toggle = card.querySelector(".bc-card-toggle");
    toggle.textContent = item.included ? "×" : "+";
    toggle.disabled = cleaningRunning;
    toggle.setAttribute("aria-label", item.included ? `Exclude ${item.name}` : `Include ${item.name}`);
    const state = itemState(item);
    const stateElement = card.querySelector(".bc-card-state");
    stateElement.toggleAttribute("data-passive", state.passive);
    stateElement.replaceChildren();
    if (item.included && WORKING_STATES.has(item.state)) {
      const spinner = document.createElement("span");
      spinner.className = "bc-spinner";
      spinner.setAttribute("aria-hidden", "true");
      stateElement.appendChild(spinner);
    }
    const label = document.createElement("strong");
    label.textContent = state.label;
    stateElement.appendChild(label);
  }

  function updateUi() {
    const summary = batchSummary(items);
    empty.hidden = items.length > 0;
    summaryLine.textContent = items.length
      ? `${items.length}/${MAX_BATCH_PHOTOS} pictures · ${summary.included} included`
      : "No pictures yet";
    overallLine.textContent = cleaningRunning
      ? `Cleaning ${summary.cleaning + summary.cleaned} of ${summary.included}`
      : detectionRunning
        ? `${summary.detecting} picture${summary.detecting === 1 ? "" : "s"} waiting for detection`
        : summary.failed
          ? `${summary.failed} failed · the remaining photos are preserved`
          : summary.ready
            ? "Detection complete · ready to Clean all"
            : summary.cleaned
              ? "Batch complete · click a thumbnail to compare"
              : "Drop up to 30 pictures to begin";
    for (const key of ["included", "excluded", "ready", "cleaned", "failed"]) {
      root.querySelector(`[data-count="${key}"]`).textContent = summary[key];
    }
    action("open_import").disabled = cleaningRunning || exporting || items.length >= MAX_BATCH_PHOTOS;
    enhanceRealityInput.disabled = cleaningRunning || exporting;
    qualityReconstructionInput.disabled = cleaningRunning || exporting;
    cloudQualityInput.disabled = cleaningRunning || exporting;
    const hasIncludedWatermark = items.some((item) =>
      item.included && item.detections.some((detection) => detection.label.startsWith("watermark")));
    action("clean_all").disabled = !canCleanBatch(items, detectionRunning || cleaningRunning || exporting)
      || (hasIncludedWatermark && !watermarkAuthorized.checked);
    action("export_all").disabled = cleaningRunning || exporting || !items.some((item) => item.included && item.state === "cleaned");
    root.toggleAttribute("aria-busy", detectionRunning || cleaningRunning || exporting);
  }

  function setStatus(message, error = "") {
    statusLine.textContent = message;
    errorLine.textContent = error;
    updateUi();
  }

  async function runDetectionQueue() {
    if (detectionRunning || disposed) return;
    detectionRunning = true;
    updateUi();
    while (!disposed) {
      const item = items.find((candidate) => candidate.included && candidate.state === "queued-detection");
      if (!item) break;
      item.state = "detecting";
      item.detail = "Loading local detector…";
      updateCard(item);
      setStatus(`Finding objects · ${item.name}`);
      try {
        const size = await imageSize(item.blob);
        const result = await findObjects(item.blob, size, (progress) => {
          item.detail = progress.status === "detecting" && progress.total
            ? `Finding objects · view ${progress.current} of ${progress.total}`
            : "Loading local detector…";
          updateCard(item);
        });
        item.detections = result.detections;
        item.cleaningPolicy = result.cleaningPolicy || {};
        item.state = "ready";
        item.detail = "";
      } catch (error) {
        item.state = "failed";
        item.error = String(error?.message || error);
      }
      updateCard(item);
      updateUi();
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    detectionRunning = false;
    setStatus(items.some((item) => item.state === "failed") ? "Detection finished with errors" : "Detection complete");
  }

  async function addFiles(files) {
    const accepted = acceptedBatchFiles(files, items.length);
    if (!accepted.length) {
      setStatus("No pictures added", items.length >= MAX_BATCH_PHOTOS ? "The 30-picture limit is full." : "Choose JPEG, PNG, or WebP pictures.");
      return;
    }
    for (const file of accepted) {
      const item = {
        id: crypto.randomUUID(),
        name: file.name || `photo-${items.length + 1}.jpg`,
        blob: file,
        output: null,
        sourceUrl: URL.createObjectURL(file),
        cleanedUrl: "",
        state: "queued-detection",
        included: true,
        detections: [],
        cleaningPolicy: {},
        detail: "",
        error: "",
        enhanced: false,
        enhancement: null
      };
      items.push(item);
      updateCard(item);
    }
    updateUi();
    void runDetectionQueue();
  }

  async function cleanAll() {
    if (!canCleanBatch(items, detectionRunning || cleaningRunning || exporting)) {
      throw new Error("Wait for every included picture to finish object detection.");
    }
    const hasIncludedWatermark = items.some((item) =>
      item.included && item.detections.some((detection) => detection.label.startsWith("watermark")));
    if (hasIncludedWatermark && !watermarkAuthorized.checked) {
      throw new Error("Confirm that you own or may remove detected watermarks.");
    }
    cleaningRunning = true;
    const shouldUseCloudQuality = cloudQualityInput.checked;
    const shouldEnhanceReality = enhanceRealityInput.checked && !shouldUseCloudQuality;
    const shouldReconstructQuality = qualityReconstructionInput.checked && !shouldUseCloudQuality;
    const queue = items.filter((item) => item.included && item.state === "ready");
    for (const item of queue) {
      item.state = "queued-clean";
      item.detail = "Queued for cleaning";
      updateCard(item);
    }
    updateUi();
    for (let photoIndex = 0; photoIndex < queue.length && !disposed; photoIndex += 1) {
      const item = queue[photoIndex];
      item.state = "cleaning";
      item.detail = `Photo ${photoIndex + 1} of ${queue.length} · preparing local AI`;
      updateCard(item);
      setStatus(`Cleaning photo ${photoIndex + 1} of ${queue.length} · ${item.name}`);
      try {
        const detections = cleanableDetections(item);
        const cleaner = shouldUseCloudQuality
          ? cleanWithCloudQuality
          : shouldReconstructQuality
            ? reconstructSelectedObjects
            : cleanSelectedObjects;
        const cleanerOptions = {
              onProgress(progress) {
                item.detail = progress.stage === "cloud-preparing"
                  ? `Photo ${photoIndex + 1}/${queue.length} · preparing private removal mask`
                  : progress.stage === "cloud-editing"
                    ? `Photo ${photoIndex + 1}/${queue.length} · perfect reconstruction in progress`
                    : progress.stage === "quality-model"
                  ? progress.total
                    ? `${progress.label} · ${Math.round(progress.current / progress.total * 100)}%`
                    : progress.label
                  : progress.stage === "quality-denoising"
                    ? `Photo ${photoIndex + 1}/${queue.length} · quality step ${progress.current}/${progress.total}`
                    : progress.stage === "loading-model"
                  ? "Downloading cleaning AI · first run only"
                  : progress.stage === "reconstructing"
                    ? `Photo ${photoIndex + 1}/${queue.length} · object ${Math.min(progress.total, progress.current + 1)}/${progress.total}`
                    : shouldUseCloudQuality
                      ? "Preparing perfect reconstruction…"
                      : shouldReconstructQuality
                      ? "Preparing scene-aware reconstruction…"
                      : "Preparing reconstruction…";
                updateCard(item);
              }
            };
        let result = { blob: item.blob };
        if (detections.length) {
          try {
            result = await cleaner(item.blob, detections, cleanerOptions);
          } catch (error) {
            if (!shouldUseCloudQuality && !shouldReconstructQuality) throw error;
            if (shouldUseCloudQuality) cloudQualityInput.checked = false;
            if (shouldReconstructQuality) qualityReconstructionInput.checked = false;
            item.detail = shouldUseCloudQuality
              ? "Perfect reconstruction unavailable · continuing with the verified local baseline"
              : "Scene-aware reconstruction unavailable · continuing with the verified local baseline";
            updateCard(item);
            result = await cleanSelectedObjects(item.blob, detections, cleanerOptions);
          }
        }
        item.output = result.blob;
        item.model = result.model || null;
        item.reconstructionStrategy = result.reconstructionStrategy || null;
        item.segmentedDetections = result.segmentedDetections ?? null;
        if (item.cleanedUrl) URL.revokeObjectURL(item.cleanedUrl);
        item.cleanedUrl = URL.createObjectURL(item.output);
        item.state = shouldEnhanceReality ? "queued-enhance" : "cleaned";
        item.qualityWorker = shouldUseCloudQuality ? {
          model: result.model,
          maskApplied: result.maskApplied === true,
          photoPersisted: result.photoPersisted === true
        } : null;
        item.detail = shouldEnhanceReality ? "Waiting for the cleaning model to be released" : "";
      } catch (error) {
        item.state = "failed";
        item.error = String(error?.message || error);
      }
      updateCard(item);
      updateUi();
      await new Promise((resolve) => requestAnimationFrame(resolve));
    }
    if (shouldEnhanceReality && !disposed) {
      setStatus("Cleaning complete · releasing local AI before enhancement");
      await Promise.allSettled([disposeObjectCleaner(), disposeQualityCleaner()]);
      for (let photoIndex = 0; photoIndex < queue.length && !disposed; photoIndex += 1) {
        const item = queue[photoIndex];
        if (item.state !== "queued-enhance") continue;
        item.state = "enhancing";
        item.detail = `Photo ${photoIndex + 1}/${queue.length} · enhancing reality`;
        updateCard(item);
        setStatus(`Enhancing reality · photo ${photoIndex + 1} of ${queue.length}`);
        try {
          const enhancement = await enhanceReality(item.output, {
            onProgress() {
              item.detail = `Photo ${photoIndex + 1}/${queue.length} · polishing detail and light`;
              updateCard(item);
            }
          });
          item.output = enhancement.blob;
          item.enhanced = true;
          item.enhancement = {
            profileId: enhancement.profileId,
            width: enhancement.width,
            height: enhancement.height,
            scale: enhancement.scale
          };
          if (item.cleanedUrl) URL.revokeObjectURL(item.cleanedUrl);
          item.cleanedUrl = URL.createObjectURL(item.output);
          item.state = "cleaned";
          item.detail = "";
        } catch (error) {
          item.state = "failed";
          item.error = String(error?.message || error);
        }
        updateCard(item);
        updateUi();
        await new Promise((resolve) => requestAnimationFrame(resolve));
      }
    }
    cleaningRunning = false;
    setStatus(items.some((item) => item.included && item.state === "failed")
      ? "Batch finished with errors · cleaned photos are ready"
      : "Batch cleaning complete · ready to compare and export");
  }

  async function exportAll() {
    const cleaned = items.filter((item) => item.included && item.state === "cleaned" && item.output);
    if (!cleaned.length) throw new Error("No included cleaned pictures are ready to export.");
    exporting = true;
    setStatus(`Building ZIP · ${cleaned.length} pictures`);
    try {
      const zip = await createZip(cleaned.map((item, index) => ({
        name: cleanedFilename(item.name, index),
        blob: item.output
      })));
      downloadZip(zip, `property-batch-cleaned-${new Date().toISOString().slice(0, 10)}.zip`);
      setStatus(`Exported ${cleaned.length} cleaned pictures`);
    } finally {
      exporting = false;
      updateUi();
    }
  }

  function showPreview(kind) {
    if (!previewItem) return;
    const cleaned = kind === "cleaned" && previewItem.cleanedUrl;
    previewImage.src = cleaned ? previewItem.cleanedUrl : previewItem.sourceUrl;
    action("preview_cleaned").disabled = !previewItem.cleanedUrl;
    action("preview_cleaned").textContent = previewItem.enhanced ? "Enhanced" : "Cleaned";
    action("preview_original").setAttribute("aria-pressed", String(!cleaned));
    action("preview_cleaned").setAttribute("aria-pressed", String(Boolean(cleaned)));
  }

  function openPreview(item) {
    previewItem = item;
    root.querySelector("[data-preview-title]").textContent = item.name;
    showPreview(item.cleanedUrl ? "cleaned" : "original");
    preview.showModal();
  }

  async function dispose() {
    disposed = true;
    for (const item of items) {
      URL.revokeObjectURL(item.sourceUrl);
      if (item.cleanedUrl) URL.revokeObjectURL(item.cleanedUrl);
    }
    disposeRealityEnhancer();
    await Promise.allSettled([
      disposeDetector(),
      disposeObjectCleaner(),
      disposeQualityCleaner()
    ]);
    root.remove();
    active = null;
    context.onClose?.();
  }

  const actions = {
    close: dispose,
    open_import: () => fileInput.click(),
    clean_all: cleanAll,
    export_all: exportAll,
    close_preview: () => preview.close(),
    preview_original: () => showPreview("original"),
    preview_cleaned: () => showPreview("cleaned")
  };

  root.addEventListener("click", async (event) => {
    const toggleId = event.target.closest("[data-toggle-item]")?.dataset.toggleItem;
    if (toggleId) {
      const item = items.find((candidate) => candidate.id === toggleId);
      if (!item || cleaningRunning) return;
      if (item.state === "detecting") {
        item.included = false;
        updateCard(item);
        updateUi();
        return;
      }
      item.included = !item.included;
      if (item.included && item.state === "excluded") {
        item.state = item.resumeState === "failed" ? "queued-detection" : (item.resumeState || "queued-detection");
      } else if (!item.included) {
        item.resumeState = item.state;
        item.state = "excluded";
      }
      updateCard(item);
      updateUi();
      if (item.included) void runDetectionQueue();
      return;
    }
    const actionName = event.target.closest("[data-action]")?.dataset.action;
    if (!actionName || !actions[actionName]) return;
    try {
      errorLine.textContent = "";
      await actions[actionName]();
    } catch (error) {
      setStatus("Action stopped", String(error?.message || error));
    }
  });
  fileInput.addEventListener("change", async (event) => {
    await addFiles(event.target.files);
    event.target.value = "";
  });
  watermarkAuthorized.addEventListener("change", updateUi);
  for (const type of ["dragenter", "dragover"]) {
    dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      dropZone.toggleAttribute("data-dragging", true);
    });
  }
  for (const type of ["dragleave", "drop"]) {
    dropZone.addEventListener(type, (event) => {
      event.preventDefault();
      dropZone.removeAttribute("data-dragging");
    });
  }
  dropZone.addEventListener("drop", (event) => addFiles(event.dataTransfer.files));

  const api = {
    root,
    actions,
    inspectStatus: () => ({
      ...batchSummary(items),
      detectionRunning,
      cleaningRunning,
      exporting,
      photos: items.map((item) => ({
        id: item.id,
        name: item.name,
        state: item.state,
        included: item.included,
        detectionCount: item.detections.length,
        enhanced: item.enhanced,
        enhancement: item.enhancement,
        model: item.model,
        reconstructionStrategy: item.reconstructionStrategy,
        segmentedDetections: item.segmentedDetections,
        detail: item.detail,
        error: item.error
      }))
    })
  };
  active = { root, api };
  updateUi();
  return api;
}
