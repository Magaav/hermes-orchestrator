import * as runtime from "../vendor/onnxruntime-web/1.27.0/ort.wasm.min.mjs";

runtime.env.wasm.wasmPaths = new URL("../vendor/onnxruntime-web/1.27.0/", import.meta.url).href;
runtime.env.wasm.numThreads = Math.max(1, Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)));
let session = null;

self.onmessage = async ({ data }) => {
  try {
    if (data.type === "init") {
      session = await runtime.InferenceSession.create(data.modelUrl, {
        executionProviders: ["wasm"],
        graphOptimizationLevel: "all"
      });
      self.postMessage({ id: data.id, result: true });
      return;
    }
    if (data.type === "run") {
      if (!session) throw new Error("The local cleaning model is not ready.");
      const outputs = await session.run({
        image: new runtime.Tensor("float32", new Float32Array(data.image.data), data.image.dims),
        mask: new runtime.Tensor("float32", new Float32Array(data.mask.data), data.mask.dims)
      });
      const output = outputs.output || Object.values(outputs)[0];
      const values = new Float32Array(output.data);
      self.postMessage({
        id: data.id,
        result: { data: values.buffer, shape: output.dims }
      }, [values.buffer]);
      return;
    }
    if (data.type === "dispose") {
      session?.release?.();
      session = null;
      self.postMessage({ id: data.id, result: true });
      return;
    }
    throw new Error(`Unsupported inference worker action: ${data.type}`);
  } catch (error) {
    self.postMessage({ id: data.id, error: String(error?.message || error) });
  }
};
