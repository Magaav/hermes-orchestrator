const DB_NAME = "wasmAgent.clientFirst.v1";
const DB_VERSION = 1;
const STORES = ["conversations", "messages", "people", "brains", "syncCursors", "artifacts"];

function openDb() {
  if (!("indexedDB" in globalThis)) return Promise.resolve(null);
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      for (const name of STORES) {
        if (!db.objectStoreNames.contains(name)) db.createObjectStore(name, { keyPath: "id" });
      }
    };
    request.onerror = () => reject(request.error || new Error("IndexedDB open failed"));
    request.onsuccess = () => resolve(request.result);
  });
}

export function createClientFirstStore() {
  let dbPromise = null;
  const memory = new Map(STORES.map((name) => [name, new Map()]));
  const db = () => {
    dbPromise ||= openDb().catch(() => null);
    return dbPromise;
  };
  async function put(storeName, value) {
    const database = await db();
    if (!STORES.includes(storeName) || !value?.id) return value;
    if (!database) {
      memory.get(storeName)?.set(value.id, value);
      return value;
    }
    await new Promise((resolve, reject) => {
      const tx = database.transaction(storeName, "readwrite");
      tx.objectStore(storeName).put(value);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error("IndexedDB write failed"));
    });
    return value;
  }
  async function all(storeName) {
    const database = await db();
    if (!STORES.includes(storeName)) return [];
    if (!database) return Array.from(memory.get(storeName)?.values() || []);
    return new Promise((resolve, reject) => {
      const tx = database.transaction(storeName, "readonly");
      const request = tx.objectStore(storeName).getAll();
      request.onsuccess = () => resolve(Array.isArray(request.result) ? request.result : []);
      request.onerror = () => reject(request.error || new Error("IndexedDB read failed"));
    });
  }
  async function get(storeName, id) {
    const database = await db();
    if (!STORES.includes(storeName) || !id) return null;
    if (!database) return memory.get(storeName)?.get(id) || null;
    return new Promise((resolve, reject) => {
      const tx = database.transaction(storeName, "readonly");
      const request = tx.objectStore(storeName).get(id);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = () => reject(request.error || new Error("IndexedDB read failed"));
    });
  }
  async function remove(storeName, id) {
    const database = await db();
    if (!STORES.includes(storeName) || !id) return false;
    if (!database) return memory.get(storeName)?.delete(id) || false;
    await new Promise((resolve, reject) => {
      const tx = database.transaction(storeName, "readwrite");
      tx.objectStore(storeName).delete(id);
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error || new Error("IndexedDB delete failed"));
    });
    return true;
  }
  return {
    schema: "hermes.wasm_agent.client_first_store.v1",
    dbName: DB_NAME,
    stores: STORES.slice(),
    ready: db(),
    put,
    get,
    all,
    remove,
  };
}
