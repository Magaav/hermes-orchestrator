import { describe, expect, it } from "vitest";
import { formatStudioElapsed } from "./time";

describe("formatStudioElapsed", () => {
  it("formats per-photo timers without creating date objects", () => {
    expect(formatStudioElapsed(0)).toBe("00:00");
    expect(formatStudioElapsed(65_999)).toBe("01:05");
    expect(formatStudioElapsed(3_661_000)).toBe("01:01:01");
  });
});
