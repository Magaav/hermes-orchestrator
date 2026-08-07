export async function exportArtifact() {
  const response = await fetch(new URL("../artifact.json", import.meta.url));
  if (!response.ok) throw new Error("Artifact descriptor could not be read.");
  const artifact = await response.json();
  const serialized = JSON.stringify(artifact, null, 2);
  if (/data:image|base64|photoBlob|processedPhoto/i.test(serialized)) {
    throw new Error("Artifact privacy validation failed.");
  }
  return new Blob([serialized], { type: "application/json" });
}
