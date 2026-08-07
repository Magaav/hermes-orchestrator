import { loadVerifiedLiteRt } from "./runtime-loader.js?v=20260727-litert3";
import { loadVerifiedModelBytes } from "./model-byte-cache.js?v=20260727-litert3";

export async function createInpaintingSession(manifest, loadingProof) {
  const liteRt = await loadVerifiedLiteRt(manifest, loadingProof);
  if (manifest.model?.status !== "verified" || !manifest.model?.url || !manifest.model?.sha256) {
    throw new Error("Local object removal is not installed: no verified LiteRT.js-compatible model is bundled.");
  }
  const modelBytes = await loadVerifiedModelBytes(manifest.model, import.meta.url, loadingProof);
  const accelerator = manifest.model.accelerator || "wasm";
  const compileStartedAt = performance.now();
  const compiled = await liteRt.loadAndCompile(modelBytes, { accelerator });
  loadingProof.compileMs = Math.round(performance.now() - compileStartedAt);
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
