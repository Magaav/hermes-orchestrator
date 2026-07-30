import moduleFactory from "@jsquash/avif/codec/enc/avif_enc.js";

type EncodeRequest = {
  id: number;
  imageData: ImageData;
};

type WorkerScope = {
  onmessage: ((event: MessageEvent<EncodeRequest>) => void) | null;
  postMessage: (message: unknown, transfer?: Transferable[]) => void;
};

const scope = globalThis as unknown as WorkerScope;
let queue = Promise.resolve();
const encoder = moduleFactory();

scope.onmessage = ({ data }) => {
  queue = queue.then(async () => {
    try {
      const module = await encoder;
      const output = module.encode(data.imageData.data, data.imageData.width, data.imageData.height, {
        quality: 100,
        qualityAlpha: -1,
        denoiseLevel: 0,
        tileRowsLog2: 0,
        tileColsLog2: 0,
        speed: 6,
        subsample: 3,
        chromaDeltaQ: false,
        sharpness: 0,
        enableSharpYUV: false,
        tune: 0,
        bitDepth: 8
      });
      if (!output) throw new Error("avif_encode_empty");
      const buffer = output.buffer;
      scope.postMessage({ id: data.id, ok: true, buffer }, [buffer]);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message.slice(0, 180) : "unknown_encode_error";
      scope.postMessage({ id: data.id, ok: false, error: message });
    }
  });
};
