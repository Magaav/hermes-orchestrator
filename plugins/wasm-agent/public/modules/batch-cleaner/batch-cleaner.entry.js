import { cleanWithCloudQuality } from "./modules/cloud-quality-cleaner.js";
import {
  acceptedBatchFiles,
  batchSummary,
  canCleanBatch,
  cleanedFilename,
  MAX_BATCH_PHOTOS
} from "./modules/batch-queue.js";
import { createZip, downloadZip } from "./modules/zip-export.js";
import { loadBatchMetrics, recordCleanedPhoto } from "./modules/batch-metrics.js";
import { transcodeToAvif } from "./modules/avif-transcoder.js";
import { runIndependentLanes } from "./modules/parallel-lanes.js";

const ROOT_ID = "batch-cleaner-root";
const ASSET_REVISION = "20260806-deeper-clean1";
const CLEANING_LANES = 10;
const WORKING_STATES = new Set([
  "queued-clean",
  "cleaning",
  "optimizing"
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
  link.href = new URL(`./batch-cleaner.css?v=${ASSET_REVISION}`, import.meta.url).href;
  link.dataset.batchCleaner = "";
  document.head.append(link);
}

export async function mount(context = {}) {
  if (active) {
    active.root.hidden = false;
    return active.api;
  }
  ensureStylesheet();
  const root = document.createElement("section");
  root.id = ROOT_ID;
  root.innerHTML = await loadText(`./batch-cleaner.html?v=${ASSET_REVISION}`);
  context.host?.classList.add("batch-cleaner-widget");
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
  let cleaningRunning = false;
  let exporting = false;
  let disposed = false;
  let previewItem = null;
  let batchTokens = 0;
  let batchFreshTokens = 0;
  let batchCachedTokens = 0;
  let lifetimeCleaned = 0;
  let activeQueueIndex = 0;
  let activeQueueTotal = 0;

  function action(name) {
    return root.querySelector(`[data-action="${name}"]`);
  }

  function itemState(item) {
    if (!item.included) return { label: "Excluded · click + to include", passive: true };
    const labels = {
      ready: "Ready for datacenter cleaning",
      optimizing: item.detail || "Optimizing transfer…",
      "queued-clean": "Queued for cleaning",
      cleaning: item.detail || "Reconstructing in the datacenter…",
      cleaned: "Cleaned · click to compare",
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
    card.dataset.uploadType = item.uploadBlob?.type || item.blob.type || "";
    card.dataset.uploadBytes = String(item.uploadBlob?.size || item.blob.size || 0);
    card.dataset.outputType = item.output?.type || "";
    card.dataset.outputBytes = String(item.output?.size || 0);
    card.dataset.progressEvents = (item.progressEvents || []).join(",");
    card.dataset.inputTokens = String(item.usage?.inputTokens || 0);
    card.dataset.cachedInputTokens = String(item.usage?.cachedInputTokens || 0);
    card.dataset.outputTokens = String(item.usage?.outputTokens || 0);
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
      ? `Processed ${activeQueueIndex} of ${activeQueueTotal} · up to ${CLEANING_LANES} active`
      : summary.failed
          ? `${summary.failed} failed · the remaining photos are preserved`
          : summary.ready
            ? "Pictures ready · click Clean all"
            : summary.cleaned
              ? "Batch complete · click a thumbnail to compare"
              : "Drop up to 30 pictures to begin";
    for (const key of ["included", "excluded", "cleaned", "failed"]) {
      root.querySelector(`[data-count="${key}"]`).textContent = summary[key];
    }
    root.querySelector('[data-count="processed"]').textContent = summary.cleaned + summary.failed;
    root.querySelector('[data-count="tokens"]').textContent = batchTokens.toLocaleString();
    root.querySelector('[data-count="fresh-tokens"]').textContent = batchFreshTokens.toLocaleString();
    root.querySelector('[data-count="cached-tokens"]').textContent = batchCachedTokens.toLocaleString();
    root.querySelector('[data-count="lifetime-cleaned"]').textContent = lifetimeCleaned.toLocaleString();
    action("open_import").disabled = cleaningRunning || exporting || items.length >= MAX_BATCH_PHOTOS;
    action("clean_all").disabled = !canCleanBatch(items, cleaningRunning || exporting);
    action("export_all").disabled = cleaningRunning || exporting || !items.some((item) => item.included && item.state === "cleaned");
    action("clean_deeper").disabled = cleaningRunning || exporting || !previewItem?.output || previewItem.cleanupPasses >= 2;
    root.toggleAttribute("aria-busy", cleaningRunning || exporting);
  }

  function setStatus(message, error = "") {
    statusLine.textContent = message;
    errorLine.textContent = error;
    updateUi();
  }

  async function addFiles(files) {
    const accepted = acceptedBatchFiles(files, items.length);
    if (!accepted.length) {
      setStatus("No pictures added", items.length >= MAX_BATCH_PHOTOS ? "The 30-picture limit is full." : "Choose JPEG, PNG, WebP, or AVIF pictures.");
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
        state: "optimizing",
        included: true,
        detail: "",
        error: "",
        enhanced: false,
        enhancement: null
      };
      items.push(item);
      updateCard(item);
    }
    updateUi();
    for (const item of items.filter((candidate) => candidate.state === "optimizing")) {
      item.detail = "Encoding high-quality AVIF for transfer…";
      updateCard(item);
      try {
        const encoded = item.blob.type === "image/avif"
          ? { blob: item.blob, inputBytes: item.blob.size, outputBytes: item.blob.size, ratio: 1, elapsedMs: 0 }
          : await transcodeToAvif(item.blob, { quality: 92, speed: 8 });
        item.uploadBlob = encoded.outputBytes < encoded.inputBytes ? encoded.blob : item.blob;
        item.transcode = {
          inputBytes: encoded.inputBytes,
          uploadBytes: item.uploadBlob.size,
          elapsedMs: encoded.elapsedMs,
          usedAvif: item.uploadBlob.type === "image/avif"
        };
        item.state = "ready";
        item.detail = "";
      } catch (error) {
        item.uploadBlob = item.blob;
        item.transcode = { inputBytes: item.blob.size, uploadBytes: item.blob.size, usedAvif: false, error: String(error) };
        item.state = "ready";
        item.detail = "";
      }
      updateCard(item);
      updateUi();
    }
    setStatus(`${accepted.length} picture${accepted.length === 1 ? "" : "s"} ready for datacenter cleaning`);
  }

  async function cleanAll() {
    if (!canCleanBatch(items, cleaningRunning || exporting)) {
      throw new Error("No included pictures are ready for cleaning.");
    }
    cleaningRunning = true;
    const queue = items.filter((item) => item.included && ["ready", "failed"].includes(item.state));
    activeQueueTotal = queue.length;
    activeQueueIndex = 0;
    for (const item of queue) {
      item.state = "queued-clean";
      item.detail = "Queued for cleaning";
      item.error = "";
      updateCard(item);
    }
    updateUi();
    async function cleanAssignment({ item, queueIndex: photoIndex, laneIndex }) {
        if (disposed) return;
        item.state = "cleaning";
        item.detail = `Lane ${laneIndex + 1} · preparing secure upload`;
        updateCard(item);
        setStatus(`Cleaning ${queue.length - activeQueueIndex} remaining · ${item.name}`);
        try {
          const cleanerOptions = {
              watermarkAuthorized: watermarkAuthorized.checked,
              onProgress(progress) {
                item.progressEvents ||= [];
                if (item.progressEvents.at(-1) !== progress.stage) {
                  item.progressEvents.push(progress.stage);
                  item.progressEvents = item.progressEvents.slice(-12);
                }
                const lane = `Lane ${laneIndex + 1}`;
                const labels = {
                  "cloud-preparing": `${lane} · preparing secure upload`,
                  "cloud-editing": `${lane} · opening progress stream`,
                  accepted: `${lane} · upload accepted`,
                  "session-starting": `${lane} · starting Codex session`,
                  "session-started": `${lane} · Codex session ready`,
                  reconstructing: `${lane} · inspecting and reconstructing`,
                  "artifact-generated": `${lane} · image generated · final quality check`,
                  finalizing: `${lane} · finalizing datacenter output`
                };
                item.detail = labels[progress.stage] || `${lane} · working…`;
                updateCard(item);
              }
          };
          const result = await cleanWithCloudQuality(item.uploadBlob || item.blob, cleanerOptions);
          await storeCleanedResult(item, result);
          item.detail = "";
        } catch (error) {
          item.state = "failed";
          item.error = String(error?.message || error);
        }
        activeQueueIndex += 1;
        statusLine.textContent = activeQueueIndex < activeQueueTotal
          ? `${activeQueueTotal - activeQueueIndex} photo${activeQueueTotal - activeQueueIndex === 1 ? "" : "s"} still cleaning`
          : "Finalizing cleaned outputs…";
        updateCard(item);
        updateUi();
        await new Promise((resolve) => setTimeout(resolve, 0));
    }
    await runIndependentLanes(queue, CLEANING_LANES, cleanAssignment);
    cleaningRunning = false;
    activeQueueIndex = 0;
    activeQueueTotal = 0;
    const hasFailures = items.some((item) => item.included && item.state === "failed");
    const hasCleaned = items.some((item) => item.included && item.state === "cleaned");
    setStatus(hasFailures
      ? hasCleaned
        ? "Batch finished with errors · cleaned photos are ready · Clean all retries failures"
        : "Batch failed · Clean all retries failed photos"
      : "Batch cleaning complete · ready to compare and export");
  }

  async function storeCleanedResult(item, result, { countCleanedPhoto = true } = {}) {
    let outputEncoding = null;
    try {
      outputEncoding = await transcodeToAvif(result.blob, { quality: 92, speed: 8 });
    } catch {
      outputEncoding = null;
    }
    item.output = outputEncoding?.outputBytes < result.blob.size ? outputEncoding.blob : result.blob;
    item.outputEncoding = outputEncoding ? {
      datacenterBytes: result.blob.size,
      outputBytes: item.output.size,
      usedAvif: item.output.type === "image/avif",
      elapsedMs: outputEncoding.elapsedMs
    } : null;
    item.model = result.model || null;
    item.reconstructionStrategy = result.reconstructionStrategy || null;
    if (item.cleanedUrl) URL.revokeObjectURL(item.cleanedUrl);
    item.cleanedUrl = URL.createObjectURL(item.output);
    item.state = "cleaned";
    item.qualityWorker = {
      model: result.model,
      sceneInspected: result.sceneInspected === true,
      photoPersisted: result.photoPersisted === true
    };
    item.usage = result.usage || {};
    const totalTokens = Math.max(0, Math.trunc(Number(item.usage.totalTokens) || 0));
    const cachedTokens = Math.max(0, Math.trunc(Number(item.usage.cachedInputTokens) || 0));
    batchTokens += totalTokens;
    batchCachedTokens += cachedTokens;
    batchFreshTokens += Math.max(0, totalTokens - cachedTokens);
    item.instructionSources = result.instructionSources || [];
    item.cleanupPasses = (item.cleanupPasses || 0) + 1;
    if (countCleanedPhoto) {
      try {
        lifetimeCleaned = (await recordCleanedPhoto(item.usage)).cleanedPhotos;
      } catch {
        lifetimeCleaned += 1;
      }
    }
  }

  async function cleanDeeper() {
    const item = previewItem;
    if (!item?.output || cleaningRunning || exporting || item.cleanupPasses >= 2) {
      throw new Error("Open a cleaned picture before running a deeper cleanup.");
    }
    cleaningRunning = true;
    activeQueueIndex = 0;
    activeQueueTotal = 1;
    item.state = "cleaning";
    item.detail = `Pass ${(item.cleanupPasses || 1) + 1} · preparing secure upload`;
    item.error = "";
    updateCard(item);
    setStatus(`Cleaning deeper · ${item.name}`);
    try {
      const result = await cleanWithCloudQuality(item.output, {
        watermarkAuthorized: watermarkAuthorized.checked,
        onProgress(progress) {
          const labels = {
            "cloud-preparing": "Preparing the cleaned photo for another pass",
            "cloud-editing": "Opening deeper-clean progress stream",
            accepted: "Deeper cleanup accepted",
            "session-starting": "Starting a fresh Codex session",
            "session-started": "Codex session ready",
            reconstructing: "Inspecting remaining tiny or unusual objects",
            "artifact-generated": "Deeper result generated · checking quality",
            finalizing: "Finalizing deeper cleanup"
          };
          item.detail = labels[progress.stage] || "Cleaning deeper…";
          updateCard(item);
        }
      });
      await storeCleanedResult(item, result, { countCleanedPhoto: false });
      item.detail = "";
      showPreview("cleaned");
      setStatus(`Deeper cleanup complete · pass ${item.cleanupPasses} · ${item.name}`);
    } catch (error) {
      item.state = "cleaned";
      item.detail = "";
      item.error = String(error?.message || error);
      throw error;
    } finally {
      cleaningRunning = false;
      activeQueueIndex = 0;
      activeQueueTotal = 0;
      updateCard(item);
      updateUi();
    }
  }

  async function exportAll() {
    const cleaned = items.filter((item) => item.included && item.state === "cleaned" && item.output);
    if (!cleaned.length) throw new Error("No included cleaned pictures are ready to export.");
    exporting = true;
    setStatus(`Building ZIP · ${cleaned.length} pictures`);
    try {
      const zip = await createZip(cleaned.map((item, index) => ({
        name: cleanedFilename(item.name, index, item.output.type === "image/avif" ? ".avif" : ""),
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
    action("preview_cleaned").textContent = "Cleaned";
    action("clean_deeper").disabled = cleaningRunning || exporting || !previewItem.output || previewItem.cleanupPasses >= 2;
    action("clean_deeper").textContent = previewItem.cleanupPasses >= 2 ? "Deeper clean complete" : "Clean deeper";
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
    root.remove();
    context.host?.classList.remove("batch-cleaner-widget");
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
    preview_cleaned: () => showPreview("cleaned"),
    clean_deeper: cleanDeeper
  };

  root.addEventListener("click", async (event) => {
    const toggleId = event.target.closest("[data-toggle-item]")?.dataset.toggleItem;
    if (toggleId) {
      const item = items.find((candidate) => candidate.id === toggleId);
      if (!item || cleaningRunning) return;
      item.included = !item.included;
      if (item.included && item.state === "excluded") {
        item.state = item.resumeState || "ready";
      } else if (!item.included) {
        item.resumeState = item.state;
        item.state = "excluded";
      }
      updateCard(item);
      updateUi();
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
      cleaningRunning,
      exporting,
      batchTokens,
      batchFreshTokens,
      batchCachedTokens,
      lifetimeCleaned,
      activeQueueIndex,
      activeQueueTotal,
      photos: items.map((item) => ({
        id: item.id,
        name: item.name,
        state: item.state,
        included: item.included,
        enhanced: item.enhanced,
        enhancement: item.enhancement,
        model: item.model,
        reconstructionStrategy: item.reconstructionStrategy,
        transcode: item.transcode,
        outputEncoding: item.outputEncoding,
        progressEvents: item.progressEvents || [],
        usage: item.usage || {},
        instructionSources: item.instructionSources || [],
        cleanupPasses: item.cleanupPasses || 0,
        detail: item.detail,
        error: item.error
      }))
    })
  };
  active = { root, api };
  try {
    lifetimeCleaned = (await loadBatchMetrics()).cleanedPhotos;
  } catch {
    lifetimeCleaned = 0;
  }
  updateUi();
  return api;
}
