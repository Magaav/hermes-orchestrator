import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./space-control.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { authenticatedClientSpaces, clientSpaceCatalog, openSpaceByReference } = await import(moduleUrl);
const spaces = [{ id: "space_realure", title: "Realure" }, { id: "space_other", title: "Other" }];
const activated = [];

const authenticated = authenticatedClientSpaces(spaces, { includeAdmin: true });
assert.deepEqual(authenticated, [
  { id: "home", name: "space-home", kind: "home" },
  { id: "admin", name: "space-admin", kind: "admin" },
  { id: "space_realure", name: "Realure", kind: "user" },
  { id: "space_other", name: "Other", kind: "user" },
]);
assert.deepEqual(clientSpaceCatalog({
  spaces: authenticated,
  activeSpaceId: "home",
  widgetIdsForSpace: (id) => id === "admin" ? ["browser", "browser", "settings"] : [],
}), {
  manifest: "space-catalog-v1",
  spaces: [
    { id: "home", name: "space-home", kind: "home", active: true, widget_ids: [] },
    { id: "admin", name: "space-admin", kind: "admin", active: false, widget_ids: ["browser", "settings"] },
    { id: "space_realure", name: "Realure", kind: "user", active: false, widget_ids: [] },
    { id: "space_other", name: "Other", kind: "user", active: false, widget_ids: [] },
  ],
  truncated: false,
});

assert.deepEqual(await openSpaceByReference("realure", { spaces, activeSpaceId: "space_other", activate: async (id) => activated.push(id) }), {
  space_id: "space_realure", space_name: "Realure", opened: true, already_open: false,
});
assert.deepEqual(activated, ["space_realure"]);
assert.equal((await openSpaceByReference("space_realure", { spaces, activeSpaceId: "space_realure", activate: async () => assert.fail() })).already_open, true);
assert.equal((await openSpaceByReference("space-admin", { spaces: authenticated, activate: async (id) => activated.push(id) })).space_id, "admin");
await assert.rejects(openSpaceByReference("missing", { spaces, activate: async () => {} }), /space_not_found/);
