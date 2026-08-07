export async function loadFixtures(loadingProof) {
  const response = await fetch(new URL("../fixtures/fixture-manifest.json", import.meta.url));
  if (!response.ok) throw new Error("Example fixture manifest is unavailable.");
  const manifest = await response.json();
  loadingProof.fixturesLoaded = true;
  return manifest;
}
