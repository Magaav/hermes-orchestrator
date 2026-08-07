export async function probeCapabilities({ requestGpuDevice = false } = {}) {
  const result = {
    canvas: Boolean(globalThis.OffscreenCanvas || globalThis.HTMLCanvasElement),
    workers: typeof Worker === "function",
    indexedDb: Boolean(globalThis.indexedDB),
    webgpu: Boolean(navigator.gpu),
    adapter: false,
    device: false,
    limits: null,
    error: null
  };
  if (!requestGpuDevice || !navigator.gpu) return result;
  try {
    const adapter = await navigator.gpu.requestAdapter();
    result.adapter = Boolean(adapter);
    if (adapter) {
      const device = await adapter.requestDevice();
      result.device = true;
      result.limits = {
        maxBufferSize: Number(device.limits.maxBufferSize),
        maxTextureDimension2D: Number(device.limits.maxTextureDimension2D)
      };
      device.destroy();
    }
  } catch (error) {
    result.error = String(error?.message || error);
  }
  return result;
}
