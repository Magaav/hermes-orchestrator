export const ARTIFACT_RECIPE_SCHEMA = "hermes.wasm_agent.artifact.recipe.v1";
export const ARTIFACT_RECEIPT_SCHEMA = "hermes.wasm_agent.artifact.receipt.v1";
export const STARS_SHELLS_GENERATOR = "asolaria.stars-shells.v1";

export function normalizeRecipe(value = {}) {
  const generator = String(value.generator || "");
  if (generator !== STARS_SHELLS_GENERATOR) throw new TypeError(`unsupported generator: ${generator}`);
  const seed = value.seed;
  if (!(seed instanceof Uint8Array) || !seed.byteLength) throw new TypeError("recipe seed bytes are required");
  if (seed.byteLength > 1 << 20) throw new RangeError("recipe seed exceeds 1 MiB");
  const maxRounds = Math.max(0, Math.min(8, Number(value.parameters?.maxRounds ?? 8) | 0));
  return {
    schema: ARTIFACT_RECIPE_SCHEMA,
    generator,
    generatorVersion: "1",
    engine: "wasm-core+js-packager",
    seed,
    parameters: { maxRounds, grid: 64 },
    limits: {
      seedBytesMax: 1 << 20,
      outputBytesMax: 64 << 20,
      network: false
    }
  };
}

export function estimateRecipe(value) {
  const recipe = normalizeRecipe(value);
  return {
    schema: ARTIFACT_RECIPE_SCHEMA,
    generator: recipe.generator,
    seedBytes: recipe.seed.byteLength,
    expectedBytes: recipe.seed.byteLength === 3796 ? 4596880 : null,
    bounded: true,
    engine: recipe.engine
  };
}

export function recipeProjection(value) {
  return [
    `g=${value.generator}`,
    `engine=${value.engine}`,
    `seed=${value.seedBytes ?? value.seed?.byteLength}`,
    `out=${value.expectedBytes ?? value.outputBytes ?? "unknown"}`,
    `ok=${value.verified ?? "pending"}`
  ].join("|");
}
