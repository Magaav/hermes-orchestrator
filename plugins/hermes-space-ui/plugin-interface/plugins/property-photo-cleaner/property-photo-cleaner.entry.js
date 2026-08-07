import { createStatus, capabilities } from "./modules/status-contract.js";
import { probeCapabilities } from "./modules/capability-probe.js";
import { correctImage } from "./modules/correction-pipeline.js";
import { downloadBlob, exportApproved } from "./modules/export-manager.js";
import { exportArtifact } from "./modules/artifact-manager.js";
import { loadFixtures } from "./modules/fixture-manifest.js";
import { createImageStore } from "./modules/image-store.js";
import { disposeRuntime } from "./modules/runtime-loader.js";
import {
  findObjects as detectObjects,
  disposeDetector
} from "./modules/object-detector.js";
import { createDetectionOverlay } from "./modules/detection-overlay.js";
import { orderDetectionsForCleaning } from "./modules/detection-mask.js";
import {
  cleanSelectedObjects,
  disposeObjectCleaner
} from "./modules/local-object-cleaner.js?v=20260727-lossless1";

const ROOT_ID = "property-photo-cleaner-root";
const BUSY_STAGES = new Set([
  "correcting",
  "loading-detector",
  "detecting",
  "loading-cleaner",
  "loading-model",
  "model-ready",
  "reconstructing"
]);
let active = null;

async function loadText(path) {
  const response = await fetch(new URL(path, import.meta.url));
  if (!response.ok) throw new Error(`Widget asset failed: ${path}`);
  return response.text();
}

function ensureStylesheet() {
  if (document.querySelector('link[data-property-photo-cleaner]')) return;
  const link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = new URL("./property-photo-cleaner.css", import.meta.url).href;
  link.dataset.propertyPhotoCleaner = "";
  document.head.appendChild(link);
}

async function decodeItem(item) {
  item.bitmap?.close?.();
  const blob = item.output || item.blob;
  try {
    item.bitmap = await createImageBitmap(blob);
  } catch {
    const url = URL.createObjectURL(blob);
    try {
      const image = new Image();
      image.src = url;
      await image.decode();
      item.bitmap = image;
    } finally {
      URL.revokeObjectURL(url);
    }
  }
  return item.bitmap;
}

export async function mount(context = {}) {
  if (active) {
    active.root.hidden = false;
    return active.api;
  }
  ensureStylesheet();
  const root = document.createElement("section");
  root.id = ROOT_ID;
  root.innerHTML = await loadText("./property-photo-cleaner.html");
  (context.mountRoot || document.body).appendChild(root);

  const status = createStatus();
  status.stage = "loading-ui";
  const store = createImageStore();
  const abort = new AbortController();
  let current = null;
  let watermarkAuthorized = false;
  let view = "cleaned";
  let detectionOverlay = null;
  const selectedDetectionIds = new Set();

  const canvas = root.querySelector("canvas");
  const statusLine = root.querySelector("[data-status]");
  const photoRail = root.querySelector("[data-photo-rail]");
  const loadingProof = context.loadingProof || {};
  const emptyState = root.querySelector("[data-empty]");
  const reviewNote = root.querySelector("[data-review-note]");
  const processing = root.querySelector("[data-processing]");
  const processingBar = root.querySelector("[data-processing-bar]");
  const processingLabel = root.querySelector("[data-processing-label]");

  function button(action) {
    return root.querySelector(`[data-action="${action}"]`);
  }

  function updateUi(options = {}) {
    const hasPhoto = Boolean(current);
    const hasOutput = Boolean(current?.output);
    const busy = BUSY_STAGES.has(status.stage);
    emptyState.hidden = hasPhoto;
    button("open_import").disabled = busy;
    button("start_auto_correction").disabled = busy || !hasPhoto;
    button("find_objects").disabled = busy || !hasPhoto;
    button("clean_objects").disabled = busy || !hasPhoto || selectedDetectionIds.size === 0;
    button("undo_clean").disabled = busy || !current?.undoOutput;
    button("approve_current").disabled = busy || !hasOutput;
    button("export_approved").disabled = busy || !store.list().some((item) => item.approved && item.output);
    button("show_original").disabled = busy || !hasPhoto;
    button("show_cleaned").disabled = busy || !hasOutput;
    button("show_original").setAttribute("aria-pressed", String(view === "original"));
    button("show_cleaned").setAttribute("aria-pressed", String(view === "cleaned"));
    if (!options.preserveReview) {
      reviewNote.textContent = !hasPhoto
        ? "No photo selected"
        : current.altered
          ? "Digitally altered · compare with the original before approval"
          : hasOutput
            ? "Enhanced · compare with the original before approval"
            : "Original photo · choose a cleaning action";
    }
  }

  function updateProcessingUi() {
    const busy = BUSY_STAGES.has(status.stage);
    const progress = status.progress || { current: 0, total: 0 };
    const currentStep = Math.min(progress.total || 0, (progress.current || 0) + 1);
    const labels = {
      correcting: "Improving light and contrast…",
      "loading-detector": "Loading the local object detector…",
      detecting: "Finding objects in this photo…",
      "loading-cleaner": "Preparing the local cleaning AI…",
      "loading-model": "Downloading the local cleaning AI (208 MB) · first run only…",
      "model-ready": "Cleaning AI ready · starting reconstruction…",
      reconstructing: `Reconstructing object ${currentStep} of ${progress.total} · about 10 seconds each · keep this tab open`
    };
    processing.hidden = !busy && status.stage !== "complete" && status.stage !== "error";
    processing.dataset.state = status.stage === "error" ? "error" : busy ? "working" : "ready";
    processingLabel.textContent = status.stage === "complete"
      ? "Cleaning complete · ready to compare with the original"
      : status.stage === "error"
        ? `Cleaning stopped · ${status.error?.message || "check the error below"}`
        : labels[status.stage] || "Working locally…";
    const determinate = status.stage === "reconstructing" && progress.total > 0;
    processingBar.removeAttribute("value");
    processingBar.max = Math.max(1, progress.total || 1);
    if (determinate) processingBar.value = Math.min(progress.total, progress.current || 0);
    root.toggleAttribute("aria-busy", busy);
  }

  function publish() {
    updateUi({ preserveReview: true });
    updateProcessingUi();
    statusLine.textContent = `${status.stage} · ${status.backend} · ${status.memoryMode} memory`;
    root.dispatchEvent(new CustomEvent("property-photo-cleaner-status", { detail: structuredClone(status) }));
  }

  async function render(item = current) {
    if (!item) return;
    const source = view === "original" ? item.blob : (item.output || item.blob);
    const bitmap = source === (item.output || item.blob)
      ? await decodeItem(item)
      : await decodeItem({ blob: source });
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const ctx = canvas.getContext("2d", { alpha: false });
    ctx.drawImage(bitmap, 0, 0);
    detectionOverlay?.show(item.detections || [], { width: bitmap.width, height: bitmap.height });
    detectionOverlay?.select(selectedDetectionIds);
    updateUi();
  }

  function renderRail() {
    photoRail.replaceChildren();
    for (const item of store.list()) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = `${item.approved ? "✓ " : ""}${item.name}`;
      button.onclick = () => {
        current = item;
        view = item.output ? "cleaned" : "original";
        render();
      };
      photoRail.appendChild(button);
    }
  }

  async function importFiles(files) {
    for (const file of files) {
      if (!file.type.startsWith("image/")) continue;
      current = store.add(file);
    }
    renderRail();
    await render();
    status.stage = current ? "idle" : "error";
    view = "original";
    publish();
  }

  async function autoCorrect() {
    if (!current) return;
    status.stage = "correcting";
    publish();
    const bitmap = await decodeItem(current);
    current.output = await correctImage(bitmap, {}, abort.signal);
    current.approved = false;
    view = "cleaned";
    await render();
    status.stage = "complete";
    publish();
  }

  async function findObjects() {
    if (!current) return;
    status.stage = "loading-detector";
    status.progress = { current: 0, total: 0 };
    publish();
    const bitmap = await decodeItem(current);
    status.stage = "detecting";
    publish();
    const result = await detectObjects(current.blob, { width: bitmap.width, height: bitmap.height }, (progress) => {
      if (progress.status !== "progress") return;
      status.progress = { current: progress.loaded || 0, total: progress.total || 0 };
      publish();
    });
    current.detections = result.detections;
    selectedDetectionIds.clear();
    status.stage = "objects-found";
    status.detection = {
      model: result.model,
      vocabulary: result.vocabulary,
      viewCount: result.viewCount,
      count: result.detections.length,
      selectedId: null
    };
    detectionOverlay.show(result.detections, { width: bitmap.width, height: bitmap.height });
    reviewNote.textContent = result.detections.length
      ? `${result.detections.length} objects found · review every box`
      : "No supported objects found · the detector cannot recognize every item";
    publish();
  }

  async function cleanObjects() {
    if (!current || !selectedDetectionIds.size) throw new Error("Select at least one object with its × button.");
    const selected = orderDetectionsForCleaning(
      (current.detections || []).filter((detection) => selectedDetectionIds.has(detection.id))
    );
    if (selected.some((detection) => detection.label === "watermark logo") && !watermarkAuthorized) {
      throw new Error("Confirm watermark ownership or authorization first.");
    }
    status.stage = "loading-cleaner";
    status.backend = "wasm";
    status.networkUsedForPhoto = false;
    publish();
    current.undoOutput = current.output || current.blob;
    current.undoDetections = current.detections;
    status.progress = { current: 0, total: selected.length };
    const result = await cleanSelectedObjects(current.output || current.blob, selected, {
      signal: abort.signal,
      onProgress(progress) {
        status.stage = progress.stage;
        status.progress = { current: progress.current, total: progress.total };
        publish();
      }
    });
    current.output = result.blob;
    status.backend = result.accelerator;
    status.model = { id: result.model, precision: "float32", cached: true, loaded: true };
    current.detections = [];
    selectedDetectionIds.clear();
    current.altered = true;
    current.approved = false;
    view = "cleaned";
    await render();
    status.stage = "complete";
    status.progress = { current: selected.length, total: selected.length };
    reviewNote.textContent = `${selected.length} object${selected.length === 1 ? "" : "s"} cleaned · compare with Original`;
    publish();
  }

  async function undoClean() {
    if (!current?.undoOutput) return;
    current.output = current.undoOutput === current.blob ? null : current.undoOutput;
    current.detections = current.undoDetections || current.detections;
    current.undoOutput = null;
    current.undoDetections = null;
    selectedDetectionIds.clear();
    view = current.output ? "cleaned" : "original";
    await render();
    status.stage = "complete";
    publish();
  }

  async function dispose() {
    abort.abort();
    disposeRuntime();
    await disposeObjectCleaner();
    await disposeDetector();
    detectionOverlay?.dispose();
    store.disposeDecoded();
    root.remove();
    active = null;
    context.onClose?.();
  }

  const actions = {
    close: dispose,
    inspect_status: () => structuredClone(status),
    open_import: () => root.querySelector('input[type="file"]').click(),
    load_examples: async () => {
      status.stage = "decoding";
      publish();
      const manifest = await loadFixtures(loadingProof);
      const demo = root.querySelector("[data-demo]");
      const demoHeader = document.createElement("div");
      demoHeader.className = "ppc-demo-header";
      const demoTitle = document.createElement("strong");
      demoTitle.textContent = "Original vs target quality";
      const demoClose = document.createElement("button");
      demoClose.type = "button";
      demoClose.dataset.action = "close_examples";
      demoClose.textContent = "Back to editor";
      demoHeader.append(demoTitle, demoClose);
      demo.replaceChildren(demoHeader, ...manifest.pairs.flatMap((pair) => ["before", "after"].map((kind) => {
        const figure = document.createElement("figure");
        const image = document.createElement("img");
        image.src = new URL(pair[kind], new URL("./fixtures/fixture-manifest.json", import.meta.url)).href;
        image.alt = `${kind === "before" ? "Original" : "Cleaned"} property photo example ${pair.id}`;
        const caption = document.createElement("figcaption");
        caption.textContent = `${pair.id} · ${kind === "before" ? "Original" : "Target quality"}`;
        figure.append(image, caption);
        return figure;
      })));
      demo.hidden = false;
      status.stage = "complete";
      publish();
      return manifest;
    },
    start_auto_correction: autoCorrect,
    find_objects: findObjects,
    clean_objects: cleanObjects,
    undo_clean: undoClean,
    cancel_processing: () => abort.abort(),
    approve_current: () => {
      if (current) current.approved = true;
      renderRail();
      updateUi();
    },
    show_original: async () => {
      view = "original";
      root.querySelector("[data-demo]").hidden = true;
      await render();
    },
    show_cleaned: async () => {
      view = "cleaned";
      root.querySelector("[data-demo]").hidden = true;
      await render();
    },
    close_examples: () => {
      root.querySelector("[data-demo]").hidden = true;
    },
    export_approved: () => exportApproved(store.list()),
    share_artifact: async () => downloadBlob(await exportArtifact(), "property-photo-cleaner.artifact.json"),
    clear_project: () => {
      store.clear();
      current = null;
      selectedDetectionIds.clear();
      renderRail();
      canvas.width = canvas.height = 1;
      detectionOverlay.clear();
      view = "cleaned";
      updateUi();
    },
    clear_model_cache: async () => globalThis.caches?.delete?.("hermes.property-photo-cleaner.models")
  };

  root.addEventListener("click", async (event) => {
    const action = event.target.closest("[data-action]")?.dataset.action;
    if (!action || !actions[action]) return;
    try {
      status.error = null;
      await actions[action]();
    } catch (error) {
      status.stage = "error";
      status.error = { code: error.name || "error", message: String(error.message || error) };
      root.querySelector("[data-error]").textContent = status.error.message;
      publish();
    }
  });
  root.querySelector('input[type="file"]').addEventListener("change", async (event) => {
    try {
      await importFiles(event.target.files);
    } catch (error) {
      status.stage = "error";
      status.error = { code: "image_decode", message: String(error.message || error) };
      root.querySelector("[data-error]").textContent = status.error.message;
      publish();
    }
  });
  root.querySelector("[data-watermark-confirm]").addEventListener("change", (event) => {
    watermarkAuthorized = event.target.checked;
  });
  detectionOverlay = createDetectionOverlay({
    layer: root.querySelector("[data-detection-layer]"),
    canvas,
    onRemoveIntent(detection) {
      if (selectedDetectionIds.has(detection.id)) selectedDetectionIds.delete(detection.id);
      else selectedDetectionIds.add(detection.id);
      detectionOverlay.select(selectedDetectionIds);
      status.detection = {
        ...(status.detection || {}),
        count: current.detections?.length || 0,
        selectedIds: [...selectedDetectionIds]
      };
      updateUi();
      reviewNote.textContent = selectedDetectionIds.size
        ? `${selectedDetectionIds.size} object${selectedDetectionIds.size === 1 ? "" : "s"} selected · click Clean objects now`
        : "No objects selected · use × to choose removals";
      publish();
    }
  });

  const api = { capabilities, actions, root };
  active = { api, root };
  status.stage = "idle";
  updateUi();
  publish();
  queueMicrotask(async () => {
    const device = await probeCapabilities({ requestGpuDevice: true });
    status.backend = device.device ? "webgpu" : device.canvas ? "wasm" : "unsupported";
    if (device.error) {
      status.error = { code: "capability_probe", message: device.error };
    }
    publish();
  });
  return api;
}
