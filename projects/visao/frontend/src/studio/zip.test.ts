import { describe, expect, it } from "vitest";
import { cleanedFilename, createZip } from "./zip";

describe("Studio ZIP export", () => {
  it("writes a valid stored ZIP with the cleaned filename", async () => {
    const name = cleanedFilename("foto original.jpg", 0);
    const zip = await createZip([{ name, blob: new Blob([new Uint8Array([1, 2, 3])], { type: "image/avif" }) }]);
    const bytes = new Uint8Array(await zip.arrayBuffer());
    const view = new DataView(bytes.buffer);

    expect(view.getUint32(0, true)).toBe(0x04034b50);
    expect(name).toBe("01-foto original-studio.avif");
    expect(new TextDecoder().decode(bytes)).toContain("01-foto original-studio.avif");
    expect(view.getUint32(bytes.length - 22, true)).toBe(0x06054b50);
  });
});
