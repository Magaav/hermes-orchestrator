import { describe, expect, it } from "vitest";
import { readStudioResult } from "./api";

function studioResponse(frames: object[]) {
  const wire = frames.map((frame) => JSON.stringify(frame)).join("\n") + "\n";
  return new Response(new Blob([wire]).stream(), {
    status: 200,
    headers: { "Content-Type": "application/x-ndjson" }
  });
}

describe("Studio stream contract", () => {
  it("assembles bounded result chunks without rendering each chunk as progress", async () => {
    const image = btoa("\u0089PNG\r\n\u001a\nproof");
    const progress: string[] = [];
    const response = studioResponse([
      { event: "accepted", detail: {} },
      {
        event: "result-start",
        detail: {
          result: {
            ok: true,
            media_type: "image/png",
            proof: { trace_id: "trace-1", usage: { available: true, total_tokens: 21 } }
          },
          chunks: 2
        }
      },
      { event: "usage", detail: { proof: { trace_id: "trace-1" } } },
      { event: "result-chunk", detail: { index: 0, data: image.slice(0, 8) } },
      { event: "result-chunk", detail: { index: 1, data: image.slice(8) } },
      { event: "complete", detail: { chunks: 2 } }
    ]);

    const result = await readStudioResult(response, ({ stage }) => progress.push(stage));

    expect(result.blob.type).toBe("image/png");
    expect(result.blob.size).toBeGreaterThan(8);
    expect(result.proof).toMatchObject({ trace_id: "trace-1", usage: { available: true, total_tokens: 21 } });
    expect(progress).toEqual(["accepted"]);
  });

  it("surfaces typed worker errors", async () => {
    const response = studioResponse([
      { event: "error", detail: { code: "studio_access_rejected", message: "Reconecte a conta." } }
    ]);

    await expect(readStudioResult(response, () => undefined)).rejects.toThrow("Reconecte a conta.");
  });

  it("rejects a missing or out-of-order image chunk", async () => {
    const response = studioResponse([
      {
        event: "result-start",
        detail: { result: { ok: true, media_type: "image/png" }, chunks: 2 }
      },
      { event: "result-chunk", detail: { index: 1, data: "broken" } },
      { event: "complete", detail: { chunks: 2 } }
    ]);

    await expect(readStudioResult(response, () => undefined)).rejects.toThrow("fora de sequência");
  });
});
