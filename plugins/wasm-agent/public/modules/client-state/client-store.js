const DB_NAME = "wasmAgent.clientFirst.v1";
const DB_VERSION = 1;
const STORES = ["conversations", "messages", "people", "brains", "syncCursors", "artifacts"];
const SNAPSHOT_SCHEMA = "hermes.wasm_agent.client_first_snapshot.v1";
const ENCRYPTED_SNAPSHOT_SCHEMA = "hermes.wasm_agent.client_first_snapshot.encrypted.v1";
const SNAPSHOT_KDF_ITERATIONS = 210000;

function bytesToBase64(bytes) {
  let text = "";
  const chunkSize = 0x8000;
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    text += String.fromCharCode(...bytes.slice(offset, offset + chunkSize));
  }
  return btoa(text);
}

function base64ToBytes(value) {
  const text = atob(String(value || ""));
  const bytes = new Uint8Array(text.length);
  for (let index = 0; index < text.length; index += 1) bytes[index] = text.charCodeAt(index);
  return bytes;
}

function browserCrypto() {
  const api = globalThis.crypto;
  if (!api?.subtle || typeof api.getRandomValues !== "function") {
    throw new Error("Encrypted client-state backup needs Web Crypto.");
  }
  return api;
}

async function deriveSnapshotKey(passphrase, salt) {
  const crypto = browserCrypto();
  const encoded = new TextEncoder().encode(String(passphrase || ""));
  if (!encoded.length) throw new Error("A passphrase is required.");
  const material = await crypto.subtle.importKey("raw", encoded, "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      hash: "SHA-256",
      salt,
      iterations: SNAPSHOT_KDF_ITERATIONS,
    },
    material,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"]
  );
}

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
  async function clear(storeName) {
    const entries = await all(storeName);
    await Promise.all(entries.map((entry) => remove(storeName, entry.id)));
    return entries.length;
  }
  async function exportSnapshot() {
    const stores = {};
    for (const storeName of STORES) stores[storeName] = await all(storeName);
    return {
      schema: SNAPSHOT_SCHEMA,
      dbName: DB_NAME,
      created_at: new Date().toISOString(),
      stores,
    };
  }
  async function importSnapshot(snapshot, options = {}) {
    if (!snapshot || snapshot.schema !== SNAPSHOT_SCHEMA || typeof snapshot.stores !== "object") {
      throw new Error("Invalid client-state snapshot.");
    }
    const counts = {};
    for (const storeName of STORES) {
      const entries = Array.isArray(snapshot.stores[storeName]) ? snapshot.stores[storeName] : [];
      if (options.clear) await clear(storeName);
      let imported = 0;
      for (const entry of entries) {
        if (!entry?.id) continue;
        await put(storeName, entry);
        imported += 1;
      }
      counts[storeName] = imported;
    }
    return { schema: SNAPSHOT_SCHEMA, imported: counts };
  }
  async function encryptSnapshot(passphrase, snapshot) {
    const crypto = browserCrypto();
    const salt = new Uint8Array(16);
    const iv = new Uint8Array(12);
    crypto.getRandomValues(salt);
    crypto.getRandomValues(iv);
    const key = await deriveSnapshotKey(passphrase, salt);
    const encoded = new TextEncoder().encode(JSON.stringify(snapshot || await exportSnapshot()));
    const encrypted = new Uint8Array(await crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, encoded));
    const stores = snapshot?.stores && typeof snapshot.stores === "object" ? snapshot.stores : {};
    return {
      schema: ENCRYPTED_SNAPSHOT_SCHEMA,
      created_at: new Date().toISOString(),
      cipher: "AES-256-GCM",
      kdf: {
        name: "PBKDF2",
        hash: "SHA-256",
        iterations: SNAPSHOT_KDF_ITERATIONS,
      },
      dbName: DB_NAME,
      store_counts: Object.fromEntries(STORES.map((storeName) => [storeName, Array.isArray(stores[storeName]) ? stores[storeName].length : 0])),
      salt: bytesToBase64(salt),
      iv: bytesToBase64(iv),
      payload: bytesToBase64(encrypted),
    };
  }
  async function decryptSnapshot(passphrase, encrypted) {
    if (!encrypted || encrypted.schema !== ENCRYPTED_SNAPSHOT_SCHEMA) {
      throw new Error("Invalid encrypted client-state snapshot.");
    }
    const key = await deriveSnapshotKey(passphrase, base64ToBytes(encrypted.salt));
    const decrypted = await browserCrypto().subtle.decrypt(
      { name: "AES-GCM", iv: base64ToBytes(encrypted.iv) },
      key,
      base64ToBytes(encrypted.payload)
    );
    const snapshot = JSON.parse(new TextDecoder().decode(new Uint8Array(decrypted)));
    if (!snapshot || snapshot.schema !== SNAPSHOT_SCHEMA) throw new Error("Decrypted snapshot has an invalid schema.");
    return snapshot;
  }
  async function exportEncrypted(passphrase) {
    return encryptSnapshot(passphrase, await exportSnapshot());
  }
  async function importEncrypted(passphrase, encrypted, options = {}) {
    return importSnapshot(await decryptSnapshot(passphrase, encrypted), options);
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
    clear,
    exportSnapshot,
    importSnapshot,
    encryptSnapshot,
    decryptSnapshot,
    exportEncrypted,
    importEncrypted,
  };
}
