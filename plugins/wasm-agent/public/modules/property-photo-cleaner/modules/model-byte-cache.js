const CACHE_NAME = "hermes.property-photo-cleaner.models.v1";

function normalizeSha256(value) {
  return String(value || "").replace(/^sha256-/i, "").toLowerCase();
}

async function sha256Hex(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

async function verifiedBytes(response, expectedSha256) {
  if (!response?.ok) {
    throw new Error(`LiteRT model download failed (${response?.status || "network error"}).`);
  }
  const bytes = await response.arrayBuffer();
  if (await sha256Hex(bytes) !== expectedSha256) {
    throw new Error("LiteRT model integrity check failed.");
  }
  return new Uint8Array(bytes);
}

export async function loadVerifiedModelBytes(model, baseUrl, loadingProof = {}) {
  const expectedSha256 = normalizeSha256(model?.sha256);
  if (!model?.url || !/^[a-f0-9]{64}$/.test(expectedSha256)) {
    throw new Error("LiteRT model requires an immutable URL and SHA-256 digest.");
  }

  const modelUrl = new URL(model.url, baseUrl);
  const cacheKey = new URL(modelUrl);
  cacheKey.searchParams.set("sha256", expectedSha256);
  const cache = globalThis.caches ? await caches.open(CACHE_NAME) : null;
  const cached = cache ? await cache.match(cacheKey.href) : null;

  if (cached) {
    try {
      const bytes = await verifiedBytes(cached, expectedSha256);
      loadingProof.modelCache = "hit";
      loadingProof.modelBytes = bytes.byteLength;
      loadingProof.modelVerified = true;
      return bytes;
    } catch {
      await cache.delete(cacheKey.href);
    }
  }

  const response = await fetch(modelUrl.href, {
    cache: "force-cache",
    credentials: "same-origin"
  });
  const clone = response.clone();
  const bytes = await verifiedBytes(response, expectedSha256);
  if (cache) await cache.put(cacheKey.href, clone);
  loadingProof.modelCache = "miss";
  loadingProof.modelBytes = bytes.byteLength;
  loadingProof.modelVerified = true;
  return bytes;
}
