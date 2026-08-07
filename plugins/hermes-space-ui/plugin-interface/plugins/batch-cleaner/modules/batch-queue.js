export const MAX_BATCH_PHOTOS = 30;

export function acceptedBatchFiles(files, currentCount = 0) {
  const capacity = Math.max(0, MAX_BATCH_PHOTOS - currentCount);
  return Array.from(files || []).filter((file) => file.type?.startsWith("image/")).slice(0, capacity);
}

export function batchSummary(items) {
  const included = items.filter((item) => item.included);
  return {
    total: items.length,
    included: included.length,
    excluded: items.length - included.length,
    detecting: included.filter((item) => item.state === "queued-detection" || item.state === "detecting").length,
    ready: included.filter((item) => item.state === "ready").length,
    cleaning: included.filter((item) =>
      ["queued-clean", "cleaning", "queued-enhance", "enhancing"].includes(item.state)).length,
    cleaned: included.filter((item) => item.state === "cleaned").length,
    failed: included.filter((item) => item.state === "failed").length
  };
}

export function canCleanBatch(items, busy = false) {
  if (busy) return false;
  const included = items.filter((item) => item.included);
  return included.some((item) => item.state === "ready")
    && included.every((item) => ["ready", "cleaned"].includes(item.state));
}

export function cleanableDetections(item) {
  const protectedLabels = new Set(item.cleaningPolicy?.protectedLabels || []);
  return (item.detections || []).filter((detection) => !protectedLabels.has(detection.label));
}

export function cleanedFilename(name, index = 0) {
  const safe = String(name || `photo-${index + 1}.jpg`).replace(/[\\/:*?"<>|]+/g, "-");
  const dot = safe.lastIndexOf(".");
  const stem = dot > 0 ? safe.slice(0, dot) : safe;
  const extension = dot > 0 ? safe.slice(dot) : ".jpg";
  return `${String(index + 1).padStart(2, "0")}-${stem}-cleaned${extension}`;
}
