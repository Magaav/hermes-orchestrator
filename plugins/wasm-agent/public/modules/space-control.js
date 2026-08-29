function normalizedSpaceReference(value) {
  return String(value || "").trim().toLocaleLowerCase();
}

function boundedText(value, limit) {
  return String(value || "").trim().slice(0, limit);
}

function normalizedSpace(space, kind = "user") {
  const id = boundedText(space?.id, 120);
  if (!id) return null;
  return {
    id,
    name: boundedText(space?.title || space?.display_name || space?.name || id, 160),
    kind: boundedText(space?.kind || kind, 24) || kind,
  };
}

export function authenticatedClientSpaces(spaces = [], { includeAdmin = false } = {}) {
  const values = [{ id: "home", name: "space-home", kind: "home" }];
  if (includeAdmin) values.push({ id: "admin", name: "space-admin", kind: "admin" });
  for (const space of Array.isArray(spaces) ? spaces : []) {
    const item = normalizedSpace(space);
    if (item) values.push(item);
  }
  return Array.from(new Map(values.map((space) => [space.id, space])).values());
}

export function clientSpaceCatalog({ spaces = [], activeSpaceId = "", widgetIdsForSpace } = {}) {
  if (typeof widgetIdsForSpace !== "function") throw new Error("space_widget_catalog_unavailable");
  const normalized = (Array.isArray(spaces) ? spaces : []).map((space) => normalizedSpace(space, space?.kind)).filter(Boolean);
  const projected = normalized.slice(0, 32).map((space) => ({
    ...space,
    active: space.id === boundedText(activeSpaceId, 120),
    widget_ids: Array.from(new Set(Array.from(widgetIdsForSpace(space.id) || [])
      .map((value) => boundedText(value, 80)).filter(Boolean))).sort().slice(0, 32),
  }));
  return { manifest: "space-catalog-v1", spaces: projected, truncated: normalized.length > projected.length };
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
