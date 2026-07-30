type WorkerResult = {
  id: number;
  ok: boolean;
  buffer?: ArrayBuffer;
  error?: string;
};

type Pending = {
  resolve: (blob: Blob) => void;
  reject: (reason: Error) => void;
  signal?: AbortSignal;
  abort?: () => void;
};

let encoder: Worker | null = null;
let sequence = 0;
let conversionQueue = Promise.resolve();
const pending = new Map<number, Pending>();

function encoderWorker() {
  if (encoder) return encoder;
  encoder = new Worker(new URL("./avif.worker.ts", import.meta.url), { type: "module" });
  encoder.onmessage = ({ data }: MessageEvent<WorkerResult>) => {
    const job = pending.get(data.id);
    if (!job) return;
    pending.delete(data.id);
    if (job.abort && job.signal) job.signal.removeEventListener("abort", job.abort);
    if (!data.ok || !data.buffer) {
      job.reject(new Error(data.error || "Não foi possível converter o resultado para AVIF."));
      return;
    }
    job.resolve(new Blob([data.buffer], { type: "image/avif" }));
  };
  encoder.onerror = () => {
    for (const job of pending.values()) job.reject(new Error("O conversor AVIF não pôde ser iniciado."));
    pending.clear();
    encoder?.terminate();
    encoder = null;
  };
  return encoder;
}

async function imageData(blob: Blob) {
  const bitmap = await createImageBitmap(blob);
  try {
    const canvas = document.createElement("canvas");
    canvas.width = bitmap.width;
    canvas.height = bitmap.height;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("O navegador não conseguiu preparar a imagem.");
    context.drawImage(bitmap, 0, 0);
    return context.getImageData(0, 0, bitmap.width, bitmap.height);
  } finally {
    bitmap.close();
  }
}

async function encodeOne(blob: Blob, signal?: AbortSignal) {
  if (signal?.aborted) throw new DOMException("Operação cancelada.", "AbortError");
  const pixels = await imageData(blob);
  if (signal?.aborted) throw new DOMException("Operação cancelada.", "AbortError");
  const id = ++sequence;
  return new Promise<Blob>((resolve, reject) => {
    const job: Pending = { resolve, reject, signal };
    if (signal) {
      job.abort = () => {
        pending.delete(id);
        reject(new DOMException("Operação cancelada.", "AbortError"));
      };
      signal.addEventListener("abort", job.abort, { once: true });
    }
    pending.set(id, job);
    encoderWorker().postMessage({ id, imageData: pixels }, [pixels.data.buffer]);
  });
}

export function losslessAvif(blob: Blob, signal?: AbortSignal) {
  const result = conversionQueue.then(() => encodeOne(blob, signal));
  conversionQueue = result.then(() => undefined, () => undefined);
  return result;
}
