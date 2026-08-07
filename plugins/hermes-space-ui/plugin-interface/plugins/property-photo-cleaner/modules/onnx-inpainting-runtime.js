let runtimePromise = null;
let webGpuRuntimePromise = null;
let workerRequestId = 0;

function rgbHwcToNchw(data, size) {
  const plane = size * size;
  const output = new Uint8Array(data.length);
  for (let pixel = 0; pixel < plane; pixel += 1) {
    output[pixel] = data[pixel * 3];
    output[plane + pixel] = data[pixel * 3 + 1];
    output[plane * 2 + pixel] = data[pixel * 3 + 2];
  }
  return output;
}

export async function createOnnxInpaintingSession(modelUrl) {
  runtimePromise ||= import(new URL("../vendor/onnxruntime-web/1.27.0/ort.wasm.min.mjs", import.meta.url).href);
  const runtime = await runtimePromise;
  runtime.env.wasm.wasmPaths = new URL("../vendor/onnxruntime-web/1.27.0/", import.meta.url).href;
  runtime.env.wasm.numThreads = Math.max(1, Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)));
  const compiled = await runtime.InferenceSession.create(modelUrl, {
    executionProviders: ["wasm"],
    graphOptimizationLevel: "all"
  });
  return {
    accelerator: "wasm",
    inputNames: compiled.inputNames,
    outputNames: compiled.outputNames,
    tensor(data, shape) {
      if (shape[3] === 3) {
        const size = shape[1];
        return new runtime.Tensor("uint8", rgbHwcToNchw(data, size), [1, 3, size, size]);
      }
      return new runtime.Tensor("uint8", data, [1, 1, shape[1], shape[2]]);
    },
    async run(input) {
      const outputs = await compiled.run(input);
      return Object.fromEntries(Object.entries(outputs).map(([name, tensor]) => [name, {
        data: tensor.data,
        shape: tensor.dims,
        toTypedArray: async () => tensor.data,
        delete() {}
      }]));
    },
    dispose() {
      compiled.release?.();
    }
  };
}

export async function createLamaInpaintingSession(modelUrl, modelSize = 512) {
  runtimePromise ||= import(new URL("../vendor/onnxruntime-web/1.27.0/ort.wasm.min.mjs", import.meta.url).href);
  const runtime = await runtimePromise;
  runtime.env.wasm.wasmPaths = new URL("../vendor/onnxruntime-web/1.27.0/", import.meta.url).href;
  runtime.env.wasm.numThreads = Math.max(1, Math.min(4, Math.floor((navigator.hardwareConcurrency || 2) / 2)));
  const compiled = await runtime.InferenceSession.create(modelUrl, {
    executionProviders: ["wasm"],
    graphOptimizationLevel: "all"
  });
  return {
    accelerator: "wasm",
    modelSize,
    inputNames: compiled.inputNames,
    outputNames: compiled.outputNames,
    tensor(data, shape) {
      return new runtime.Tensor("float32", data, shape);
    },
    async run(input) {
      const outputs = await compiled.run(input);
      return Object.fromEntries(Object.entries(outputs).map(([name, tensor]) => [name, {
        data: tensor.data,
        shape: tensor.dims,
        toTypedArray: async () => tensor.data,
        delete() {}
      }]));
    },
    dispose() {
      compiled.release?.();
    }
  };
}

export async function createLamaWorkerSession(modelUrl, modelSize = 256) {
  const worker = new Worker(new URL("../workers/inference-worker.js", import.meta.url), { type: "module" });
  const pending = new Map();
  worker.onmessage = ({ data }) => {
    const pendingRequest = pending.get(data.id);
    if (!pendingRequest) return;
    pending.delete(data.id);
    if (data.error) pendingRequest.reject(new Error(data.error));
    else pendingRequest.resolve(data.result);
  };
  worker.onerror = (event) => {
    const error = new Error(event.message || "The local inference worker stopped.");
    for (const pendingRequest of pending.values()) pendingRequest.reject(error);
    pending.clear();
  };
  function request(type, payload = {}, transfers = []) {
    const id = ++workerRequestId;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      worker.postMessage({ id, type, ...payload }, transfers);
    });
  }
  await request("init", { modelUrl, modelSize });
  return {
    accelerator: "wasm-worker",
    modelSize,
    tensor(data, shape) {
      return { data, shape, delete() {} };
    },
    async run(input) {
      const result = await request("run", {
        image: { data: input.image.data.buffer, dims: input.image.shape },
        mask: { data: input.mask.data.buffer, dims: input.mask.shape }
      }, [input.image.data.buffer, input.mask.data.buffer]);
      const values = new Float32Array(result.data);
      return {
        output: {
          data: values,
          shape: result.shape,
          toTypedArray: async () => values,
          delete() {}
        }
      };
    },
    dispose() {
      worker.terminate();
      const error = new DOMException("Inpainting worker disposed.", "AbortError");
      for (const pendingRequest of pending.values()) pendingRequest.reject(error);
      pending.clear();
      return Promise.resolve();
    }
  };
}

export async function createLamaWebGpuSession(modelUrl, modelSize = 512) {
  if (!navigator.gpu) throw new Error("WebGPU is not available in this browser.");
  webGpuRuntimePromise ||= import(new URL("../vendor/onnxruntime-web/1.27.0/ort.webgpu.min.mjs", import.meta.url).href);
  const runtime = await webGpuRuntimePromise;
  runtime.env.wasm.wasmPaths = new URL("../vendor/onnxruntime-web/1.27.0/", import.meta.url).href;
  runtime.env.wasm.numThreads = 1;
  const compiled = await runtime.InferenceSession.create(modelUrl, {
    executionProviders: ["webgpu"],
    graphOptimizationLevel: "all"
  });
  return {
    accelerator: "webgpu",
    modelSize,
    inputNames: compiled.inputNames,
    outputNames: compiled.outputNames,
    tensor(data, shape) {
      return new runtime.Tensor("float32", data, shape);
    },
    async run(input) {
      const outputs = await compiled.run(input);
      return Object.fromEntries(Object.entries(outputs).map(([name, tensor]) => [name, {
        data: tensor.data,
        shape: tensor.dims,
        toTypedArray: async () => tensor.getData?.() || tensor.data,
        delete() {
          tensor.dispose?.();
        }
      }]));
    },
    dispose() {
      compiled.release?.();
    }
  };
}
