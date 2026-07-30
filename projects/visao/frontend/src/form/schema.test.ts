import { describe, expect, it } from "vitest";
import { checklistGroups, emptyPayload, requiredFieldKeys, steps } from "./schema";

describe("Visão form contract", () => {
  it("keeps the six-step workflow and unique required keys", () => {
    expect(steps).toHaveLength(6);
    expect(new Set(requiredFieldKeys).size).toBe(requiredFieldKeys.length);
  });

  it("initializes every checklist document exactly once", () => {
    const documentIDs = checklistGroups.flatMap((group) => group.documents.map((document) => document.id));
    const payload = emptyPayload();
    expect(Object.keys(payload.checklist)).toHaveLength(documentIDs.length);
    expect(new Set(documentIDs).size).toBe(documentIDs.length);
    expect(Object.values(payload.checklist).every((entry) => entry.status === "pending")).toBe(true);
  });
});
