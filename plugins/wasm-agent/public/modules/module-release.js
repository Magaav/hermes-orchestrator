const SCHEMA = "hermes.wasm_agent.module_release.v1";
const SHA256 = /^[a-f0-9]{64}$/;

export function validModuleRelease(value) {
  return Boolean(value && value.schema === SCHEMA && SHA256.test(String(value.release_id || ""))
    && value.entry?.web === "app.js" && value.entry?.android === "android-app.js");
}

export async function fetchModuleRelease(fetchRef = globalThis.fetch) {
  try {
    const response = await fetchRef("/module-release.json", { cache: "no-store", headers: { Accept: "application/json" } });
    const value = response.ok ? await response.json() : null;
    return validModuleRelease(value) ? value : null;
  } catch { return null; }
}

export function moduleEntryUrl(manifest, android = false) {
  const entry = android ? "android-app.js" : "app.js";
  return `/${entry}?v=${manifest?.release_id || "fallback"}`;
}
