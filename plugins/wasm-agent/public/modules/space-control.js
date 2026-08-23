function normalizedSpaceReference(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

export async function openSpaceByReference(reference, { spaces = [], activeSpaceId = "", activate } = {}) {
  const requested = String(reference || "").trim();
  if (!requested) throw new Error("space_reference_missing");
  if (typeof activate !== "function") throw new Error("space_control_unavailable");
  const normalized = normalizedSpaceReference(requested);
  const matches = spaces.filter((space) => {
    const values = [space?.id, space?.title, space?.name, space?.display_name];
    return values.some((value) => normalizedSpaceReference(value) === normalized);
  });
  if (!matches.length) throw new Error("space_not_found");
  if (matches.length > 1) throw new Error("space_reference_ambiguous");
  const space = matches[0];
  const spaceId = String(space.id || "").trim();
  if (!spaceId) throw new Error("space_id_missing");
  const alreadyOpen = spaceId === String(activeSpaceId || "").trim();
  if (!alreadyOpen) await activate(spaceId);
  return { space_id: spaceId, space_name: String(space.title || space.display_name || space.name || spaceId), opened: true, already_open: alreadyOpen };
}
