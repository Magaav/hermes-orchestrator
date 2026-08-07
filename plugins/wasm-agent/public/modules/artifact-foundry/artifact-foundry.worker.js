import { generateArtifact } from "./runtime.js";

self.addEventListener("message", async (event) => {
  const request = event.data || {};
  if (request.type !== "generate") return;
  try {
    const seed = new Uint8Array(request.seed);
    const result = await generateArtifact({
      generator: request.generator,
      seed,
      parameters: request.parameters
    });
    self.postMessage({
      type: "complete",
      requestId: request.requestId,
      receipt: result.receipt,
      projection: result.projection,
      output: result.output.buffer
    }, [result.output.buffer]);
  } catch (error) {
    self.postMessage({
      type: "error",
      requestId: request.requestId,
      error: String(error?.message || error)
    });
  }
});
