const ENDPOINT = "/property-photo-cleaner/edit";

function blobToBase64(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Could not read the property photo."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(blob);
  });
}

function base64ToBlob(encoded, mediaType) {
  const bytes = Uint8Array.from(atob(encoded), (character) => character.charCodeAt(0));
  return new Blob([bytes], { type: mediaType });
}

export async function cleanSelectedObjects(source, detections, { signal } = {}) {
  const response = await fetch(ENDPOINT, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      cloud_consent: true,
      media_type: source.type || "image/jpeg",
      image_base64: await blobToBase64(source),
      objects: detections.map(({ label }) => label)
    }),
    signal
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok || !payload.ok) {
    throw new Error(payload?.error?.message || "High-quality object cleaning failed.");
  }
  return {
    blob: base64ToBlob(payload.image_base64, payload.media_type || "image/jpeg"),
    model: payload.model,
    persisted: payload.photo_persisted
  };
}
