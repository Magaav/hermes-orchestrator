const DB_NAME = "hermes.batch-cleaner.metrics";
const STORE_NAME = "counters";
const LIFETIME_KEY = "lifetime";
let writeLane = Promise.resolve();

export const EMPTY_METRICS = Object.freeze({ cleanedPhotos: 0, reportedTokens: 0 });

function nonnegativeInteger(value) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.max(0, Math.trunc(number)) : 0;
}

export function nextMetrics(current, usage = {}) {
  return {
    cleanedPhotos: nonnegativeInteger(current?.cleanedPhotos) + 1,
    reportedTokens: nonnegativeInteger(current?.reportedTokens) + nonnegativeInteger(usage.totalTokens)
  };
}

function openMetricsDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, 1);
    request.onerror = () => reject(request.error);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE_NAME);
    request.onsuccess = () => resolve(request.result);
  });
}

function requestResult(request) {
  return new Promise((resolve, reject) => {
    request.onerror = () => reject(request.error);
    request.onsuccess = () => resolve(request.result);
  });
}

export async function loadBatchMetrics() {
  const database = await openMetricsDb();
  try {
    const store = database.transaction(STORE_NAME).objectStore(STORE_NAME);
    const value = await requestResult(store.get(LIFETIME_KEY));
    return {
      cleanedPhotos: nonnegativeInteger(value?.cleanedPhotos),
      reportedTokens: nonnegativeInteger(value?.reportedTokens)
    };
  } finally {
    database.close();
  }
}

async function writeCleanedPhoto(usage) {
  const current = await loadBatchMetrics();
  const next = nextMetrics(current, usage);
  const database = await openMetricsDb();
  try {
    const store = database.transaction(STORE_NAME, "readwrite").objectStore(STORE_NAME);
    await requestResult(store.put(next, LIFETIME_KEY));
    return next;
  } finally {
    database.close();
  }
}

export function recordCleanedPhoto(usage = {}) {
  const operation = writeLane.then(() => writeCleanedPhoto(usage));
  writeLane = operation.catch(() => {});
  return operation;
}
