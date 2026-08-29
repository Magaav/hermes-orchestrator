"use strict";

async function clearWebShellCache(targetSession, log = () => {}) {
  const storages = ["http", "serviceworkers", "cachestorage", "localstorage"];
  try {
    await targetSession.clearCache();
    await targetSession.clearStorageData({ storages: storages.slice(1) });
    log("web-cache-cleared", { storages });
    return { ok: true, storages };
  } catch (error) {
    const reason = String(error?.message || error);
    log("web-cache-clear-failed", { reason });
    return { ok: false, error: reason };
  }
}

module.exports = { clearWebShellCache };
