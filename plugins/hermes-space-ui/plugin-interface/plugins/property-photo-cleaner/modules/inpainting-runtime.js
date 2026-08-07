import { loadVerifiedLiteRt } from "./runtime-loader.js";

export async function createInpaintingSession(manifest, loadingProof) {
  const liteRt = await loadVerifiedLiteRt(manifest, loadingProof);
  if (manifest.model?.status !== "verified" || !manifest.model?.url || !manifest.model?.sha256) {
    throw new Error("Local object removal is not installed: no verified LiteRT.js-compatible model is bundled.");
  }
  const modelUrl = new URL(manifest.model.url, import.meta.url).href;
  const accelerator = manifest.model.accelerator || "wasm";
  const compiled = await liteRt.loadAndCompile(modelUrl, { accelerator });
  loadingProof.modelLoaded = true;
  return {
    accelerator,
    compiled,
    tensor(data, shape) {
      return new liteRt.Tensor(data, shape);
    },
    run(input) {
      return compiled.run(input);
    },
    dispose() {
      compiled.delete?.();
    }
  };
}
