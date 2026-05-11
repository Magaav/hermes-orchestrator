#!/usr/bin/env node
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

delete globalThis.indexedDB;

const here = dirname(fileURLToPath(import.meta.url));
const source = await readFile(resolve(here, "../public/modules/client-state/client-store.js"), "utf8");
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const { createClientFirstStore } = await import(moduleUrl);
const store = createClientFirstStore();
assert.equal(store.schema, "hermes.wasm_agent.client_first_store.v1");
assert.ok(store.stores.includes("people"));
assert.ok(store.stores.includes("messages"));

await store.ready;

await store.put("people", {
  id: "friendships",
  friendships: [{ id: "fr_1", status: "accepted" }],
  unreadByConversation: { "dm-1-2": 2 },
  syncCursor: "10",
});
assert.equal((await store.get("people", "friendships")).syncCursor, "10");

await store.put("conversations", {
  id: "dm-1-2",
  peer: { id: "2", label: "Bob" },
  unread_count: 2,
});
await store.put("messages", {
  id: "dm-1-2:10",
  conversation_id: "dm-1-2",
  message: { id: "sync_10", sync_event_id: "10", content: "hello" },
});
await store.put("conversations", {
  id: "space-share-chat",
  kind: "shared-space",
  shared_space_id: "share-chat",
  sync_cursor: "22",
});
await store.put("syncCursors", {
  id: "shared-space:share-chat",
  cursor: "22",
});

assert.equal((await store.all("conversations")).length, 2);
assert.equal((await store.all("messages"))[0].message.content, "hello");
assert.equal((await store.get("syncCursors", "shared-space:share-chat")).cursor, "22");

assert.equal(await store.remove("messages", "dm-1-2:10"), true);
assert.equal(await store.get("messages", "dm-1-2:10"), null);
assert.equal(await store.remove("messages", "missing"), false);
