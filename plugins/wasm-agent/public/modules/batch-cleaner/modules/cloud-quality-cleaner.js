function blobBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Could not encode the property photo."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(blob);
  });
}

export async function cleanWithCloudQuality(sourceBlob, options = {}) {
  options.onProgress?.({ stage: "cloud-preparing", current: 0, total: 1 });
  const imageBase64 = await blobBase64(sourceBlob);
  options.onProgress?.({ stage: "cloud-editing", current: 0, total: 1 });
  const response = await fetch("/property-photo-cleaner/edit/stream", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cloud_consent: true,
      watermark_authorized: options.watermarkAuthorized === true,
      media_type: sourceBlob.type || "image/jpeg",
      image_base64: imageBase64
    }),
    signal: options.signal
  });
  if (!response.ok || !response.body) {
    throw new Error(`Datacenter worker failed with HTTP ${response.status}.`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let result = null;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const frame = JSON.parse(line);
      if (frame.event === "error") {
        throw new Error(frame.detail?.message || "Datacenter reconstruction failed.");
      }
      if (frame.event === "complete") {
        result = frame.detail?.result || null;
      } else {
        options.onProgress?.({ stage: frame.event, detail: frame.detail || {} });
      }
    }
    if (done) break;
  }
  if (!result?.ok || !result.image_base64) {
    throw new Error("Datacenter worker completed without an image.");
  }
  const bytes = Uint8Array.from(atob(result.image_base64), (character) => character.charCodeAt(0));
  options.onProgress?.({ stage: "complete", current: 1, total: 1 });
  return {
    blob: new Blob([bytes], { type: result.media_type || "image/jpeg" }),
    model: result.model,
    accelerator: "codex-datacenter",
    sceneInspected: result.scene_inspected === true,
    photoPersisted: result.photo_persisted === true,
    completion: result.proof?.completion || "",
    usage: result.proof?.usage || {},
    instructionSources: result.proof?.instruction_sources || []
  };
}
