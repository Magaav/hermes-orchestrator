import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(new URL("./space-control.js", import.meta.url), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { openSpaceByReference } = await import(moduleUrl);
const spaces = [{ id: "space_realure", title: "Realure" }, { id: "space_other", title: "Other" }];
const activated = [];

assert.deepEqual(await openSpaceByReference("realure", { spaces, activeSpaceId: "space_other", activate: async (id) => activated.push(id) }), {
  space_id: "space_realure", space_name: "Realure", opened: true, already_open: false,
});
assert.deepEqual(activated, ["space_realure"]);
assert.equal((await openSpaceByReference("space_realure", { spaces, activeSpaceId: "space_realure", activate: async () => assert.fail() })).already_open, true);
await assert.rejects(openSpaceByReference("missing", { spaces, activate: async () => {} }), /space_not_found/);
