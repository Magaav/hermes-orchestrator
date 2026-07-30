import { losslessAvif } from "./avif";

export type StudioProgress = {
  stage: string;
  detail?: Record<string, unknown>;
};

export type StudioTokenUsage = {
  available: boolean;
  complete: boolean;
  source?: "provider_reported";
  main_available: boolean;
  image_available: boolean;
  main_input_tokens: number;
  cached_main_input_tokens: number;
  main_output_tokens: number;
  reasoning_output_tokens: number;
  image_input_tokens: number;
  image_output_tokens: number;
  image_text_input_tokens: number;
  image_source_input_tokens: number;
  total_tokens: number;
};

export type StudioProof = {
  trace_id?: string;
  response_id?: string;
  provider_model?: string;
  elapsed_ms?: number;
  usage?: StudioTokenUsage;
  [key: string]: unknown;
};

export type StudioUsagePeriod = "day" | "month" | "year";
export type StudioUsageScope = "me" | "all";

export type StudioSessionSummary = {
  id: string;
  createdAt: string;
  updatedAt: string;
  photoCount: number;
  totalElapsedMs: number;
  totalBytes: number;
};

export type StudioSessionPhoto = {
  id: string;
  sourceName: string;
  sourceType: string;
  outputType: string;
  sourceBytes: number;
  outputBytes: number;
  elapsedMs: number;
  createdAt: string;
  sourceUrl: string;
  outputUrl: string;
  proof: StudioProof;
};

export type StudioSession = StudioSessionSummary & {
  photos: StudioSessionPhoto[];
};

export type StudioUsageDashboard = {
  period: StudioUsagePeriod;
  scope: StudioUsageScope;
  anchor: string;
  range: {
    from: string;
    to: string;
    label: string;
    previous: string;
    next: string;
  };
  summary: {
    pictures: number;
    meteredPictures: number;
    completePictures: number;
    partialPictures: number;
    unreportedPictures: number;
    totalTokens: number;
    averageTokens: number;
    mainTokens: number;
    imageTokens: number;
  };
  series: Array<{
    key: string;
    label: string;
    tokens: number;
    pictures: number;
  }>;
  users: Array<{
    id: number;
    name: string;
    pictures: number;
    meteredPictures: number;
    totalTokens: number;
    averageTokens: number;
  }>;
};

export type StudioAccessStatus = {
  account: {
    state: "connected" | "disconnected" | "checking" | "unknown";
    authMode?: string;
    planType?: string;
  };
  runtime: {
    state: "ready" | "unavailable";
    errorClass?: string;
  };
  datacenter: {
    state: "ready" | "unavailable";
  };
  login: StudioLoginStatus;
  checkedAt: string;
};

export type StudioLoginStatus = {
  state: "idle" | "pending" | "completed" | "failed";
  verificationUrl?: string;
  userCode?: string;
  message?: string;
};

async function jsonResponse<T>(response: Response, fallback: string): Promise<T> {
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.message || fallback);
  return body as T;
}

export async function getStudioAccessStatus(signal?: AbortSignal) {
  const response = await fetch("/api/studio/status", {
    credentials: "same-origin",
    signal
  });
  return jsonResponse<StudioAccessStatus>(response, "Não foi possível verificar o acesso do Studio.");
}

export async function startStudioCodexLogin() {
  const response = await fetch("/api/studio/login/start", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
  return jsonResponse<{ login: StudioLoginStatus }>(response, "Não foi possível iniciar o acesso ao Codex.");
}

export async function getStudioUsage(
  period: StudioUsagePeriod,
  scope: StudioUsageScope,
  anchor: string,
  signal?: AbortSignal
) {
  const query = new URLSearchParams({ period, scope, anchor });
  const response = await fetch(`/api/studio/usage?${query}`, {
    credentials: "same-origin",
    signal
  });
  return jsonResponse<StudioUsageDashboard>(response, "Não foi possível carregar o uso do Studio.");
}

export async function createStudioSession() {
  const response = await fetch("/api/studio/sessions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  });
  return jsonResponse<StudioSession>(response, "Não foi possível criar a sessão do Studio.");
}

export async function listStudioSessions(signal?: AbortSignal) {
  const response = await fetch("/api/studio/sessions", {
    credentials: "same-origin",
    signal
  });
  return jsonResponse<{ items: StudioSessionSummary[]; count: number }>(
    response,
    "Não foi possível carregar as sessões do Studio."
  );
}

export async function getStudioSession(id: string, signal?: AbortSignal) {
  const response = await fetch(`/api/studio/sessions/${encodeURIComponent(id)}`, {
    credentials: "same-origin",
    signal
  });
  return jsonResponse<StudioSession>(response, "Não foi possível abrir a sessão do Studio.");
}

export async function deleteStudioSession(id: string) {
  const response = await fetch(`/api/studio/sessions/${encodeURIComponent(id)}`, {
    method: "DELETE",
    credentials: "same-origin"
  });
  return jsonResponse<{ deleted: boolean }>(response, "Não foi possível excluir a sessão do Studio.");
}

export async function saveStudioSessionPhoto(
  sessionId: string,
  input: {
    source: File;
    output: Blob;
    elapsedMs: number;
    proof: StudioProof;
  }
) {
  const traceId = String(input.proof.trace_id || "");
  if (!traceId) throw new Error("O tratamento não retornou o identificador necessário para arquivar a foto.");
  const data = new FormData();
  data.append("traceId", traceId);
  data.append("elapsedMs", String(Math.max(0, Math.round(input.elapsedMs))));
  data.append("source", input.source, input.source.name);
  data.append("output", input.output, `${input.source.name.replace(/\.[^.]+$/, "") || "foto"}-studio.avif`);
  const response = await fetch(`/api/studio/sessions/${encodeURIComponent(sessionId)}/photos`, {
    method: "POST",
    credentials: "same-origin",
    body: data
  });
  return jsonResponse<StudioSessionPhoto>(response, "Não foi possível arquivar a foto na sessão.");
}

type StudioResult = {
  ok: boolean;
  image_base64: string;
  media_type: string;
  proof?: StudioProof;
};

function fileBase64(file: File) {
  return new Promise<string>((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error || new Error("Não foi possível ler a foto."));
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1] || "");
    reader.readAsDataURL(file);
  });
}

function resultBlob(result: StudioResult) {
  const binary = atob(result.image_base64);
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index);
  return new Blob([bytes], { type: result.media_type || "image/jpeg" });
}

export async function readStudioResult(
  response: Response,
  onProgress: (progress: StudioProgress) => void
) {
  if (!response.ok || !response.body) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || "O Studio não conseguiu iniciar o tratamento.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const imageChunks: string[] = [];
  let buffer = "";
  let result: StudioResult | null = null;
  let expectedChunks = 0;
  let completed = false;
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const lines = buffer.split("\n");
    buffer = done ? "" : lines.pop() || "";
    for (const line of lines) {
      if (!line.trim()) continue;
      const frame = JSON.parse(line);
      if (frame.event === "error") {
        throw new Error(frame.detail?.message || "Não foi possível tratar esta foto.");
      }
      if (frame.event === "result-start") {
        result = frame.detail?.result || null;
        expectedChunks = Math.max(0, Number(frame.detail?.chunks) || 0);
        continue;
      }
      if (frame.event === "result-chunk") {
        if (Number(frame.detail?.index) !== imageChunks.length) {
          throw new Error("O Studio recebeu a imagem fora de sequência.");
        }
        imageChunks.push(String(frame.detail?.data || ""));
        continue;
      }
      if (frame.event === "complete") {
        completed = Number(frame.detail?.chunks) === expectedChunks;
        continue;
      }
      if (frame.event === "usage") continue;
      onProgress({ stage: frame.event, detail: frame.detail || {} });
    }
    if (done) break;
  }
  if (!completed || !result?.ok || !expectedChunks || imageChunks.length !== expectedChunks) {
    throw new Error("O tratamento terminou sem gerar uma imagem.");
  }
  result.image_base64 = imageChunks.join("");
  return { blob: resultBlob(result), proof: result.proof || {} };
}

export async function cleanStudioPhoto(
  file: File,
  options: {
    watermarkAuthorized: boolean;
    signal: AbortSignal;
    onProgress: (progress: StudioProgress) => void;
  }
) {
  options.onProgress({ stage: "preparing" });
  const imageBase64 = await fileBase64(file);
  const response = await fetch("/api/studio/clean", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      wire_version: 2,
      cloud_consent: true,
      watermark_authorized: options.watermarkAuthorized,
      source_name: file.name,
      media_type: file.type || "image/jpeg",
      image_base64: imageBase64
    }),
    signal: options.signal
  });
  const result = await readStudioResult(response, options.onProgress);
  options.onProgress({ stage: "encoding-avif" });
  const avif = await losslessAvif(result.blob, options.signal);
  return {
    blob: avif,
    proof: {
      ...result.proof,
      delivery: {
        format: "avif",
        lossless: true,
        provider_bytes: result.blob.size,
        avif_bytes: avif.size
      }
    }
  };
}
