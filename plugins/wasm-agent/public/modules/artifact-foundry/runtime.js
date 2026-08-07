import {
  ARTIFACT_RECEIPT_SCHEMA,
  normalizeRecipe,
  recipeProjection
} from "./recipe.js";

let corePromise;

async function sha256(bytes) {
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((value) => value.toString(16).padStart(2, "0")).join("");
}

async function loadCore() {
  if (!corePromise) {
    corePromise = fetch(new URL("./artifact_generator.wasm", import.meta.url))
      .then((response) => {
        if (!response.ok) throw new Error(`artifact generator WASM failed: ${response.status}`);
        return WebAssembly.instantiateStreaming(response, {
          env: {
            abort() {
              throw new Error("artifact generator WASM aborted");
            }
          }
        });
      })
      .then(({ instance }) => instance);
  }
  return corePromise;
}

function shellOf(ties) {
  let shell = 0;
  let rung = 1;
  while (rung < ties && shell < 12) {
    rung *= 3;
    shell += 1;
  }
  return shell;
}

function shellCount(bytes) {
  const records = Math.floor(bytes.length / 3);
  const counts = new Uint32Array(64 ** 3);
  for (let index = 0; index < records; index += 1) {
    const offset = index * 3;
    const key = (bytes[offset] >> 2) * 4096 + (bytes[offset + 1] >> 2) * 64 + (bytes[offset + 2] >> 2);
    counts[key] += 1;
  }
  const shells = new Set();
  for (const ties of counts) if (ties >= 2) shells.add(shellOf(ties));
  return shells.size;
}

async function pumpedSeed(seed, maxRounds) {
  const instance = await loadCore();
  const { exports } = instance;
  if (seed.byteLength > exports.inputCapacity()) throw new RangeError("seed exceeds WASM input capacity");
  new Uint8Array(exports.memory.buffer, exports.inputPtr(), seed.byteLength).set(seed);
  let rounds = 0;
  let previousShells = 0;
  let current = seed;
  while (rounds < maxRounds) {
    const shells = shellCount(current);
    if (shells && shells === previousShells && rounds >= 2) break;
    previousShells = shells;
    rounds += 1;
    const length = exports.pump(seed.byteLength, rounds);
    if (length < 0) throw new Error(`WASM pump rejected recipe: ${length}`);
    current = new Uint8Array(exports.memory.buffer, exports.outputPtr(), length).slice();
  }
  return { bytes: current, rounds };
}

class Writer {
  constructor() {
    this.bytes = [];
  }
  u32(value) {
    for (let shift = 0; shift < 32; shift += 8) this.bytes.push((value >>> shift) & 255);
  }
  u64(value) {
    const low = value >>> 0;
    const high = Math.floor(value / 4294967296) >>> 0;
    this.u32(low);
    this.u32(high);
  }
  string(value) {
    const encoded = new TextEncoder().encode(value);
    this.u64(encoded.length);
    this.bytes.push(...encoded);
  }
  raw(value) {
    this.bytes.push(...value);
  }
  finish() {
    return Uint8Array.from(this.bytes);
  }
}

function f32Bytes(value) {
  const view = new DataView(new ArrayBuffer(4));
  view.setFloat32(0, value, true);
  return new Uint8Array(view.buffer);
}

function buildStars(bytes) {
  const records = Math.floor(bytes.length / 3);
  const counts = new Uint32Array(64 ** 3);
  const keys = new Uint32Array(records);
  for (let index = 0; index < records; index += 1) {
    const offset = index * 3;
    const key = (bytes[offset] >> 2) * 4096 + (bytes[offset + 1] >> 2) * 64 + (bytes[offset + 2] >> 2);
    keys[index] = key;
    counts[key] += 1;
  }
  const stars = [];
  const cubes = new Map();
  for (let index = 0; index < records; index += 1) {
    const ties = counts[keys[index]];
    if (ties < 2) continue;
    const offset = index * 3;
    const shell = shellOf(ties);
    if (!cubes.has(shell)) cubes.set(shell, new Uint32Array(64 ** 3));
    const x = bytes[offset] >> 2;
    const y = bytes[offset + 1] >> 2;
    const z = bytes[offset + 2] >> 2;
    cubes.get(shell)[x * 4096 + y * 64 + z] += 1;
    let gradient = 0;
    if (index > 0 && index < records - 1) {
      for (let axis = 0; axis < 3; axis += 1) {
        gradient += Math.abs(Math.floor((bytes[offset + 3 + axis] - bytes[offset - 3 + axis]) / 2));
      }
    }
    stars.push({ time: index, shell, gradient, x, y, z });
  }
  for (const cube of cubes.values()) {
    for (let index = 0; index < cube.length; index += 1) if (cube[index] < 2) cube[index] = 0;
  }
  return { stars, cubes: [...cubes.entries()].sort(([a], [b]) => a - b) };
}

function tensorData(starField) {
  const tensors = [];
  for (const [shell, cube] of starField.cubes) tensors.push({ name: `shell_${shell}_cube`, shape: [64, 64, 64], values: cube });
  for (const [shell, cube] of starField.cubes) {
    for (const [plane, axis] of [["A", 0], ["B", 1], ["C", 2]]) {
      const values = new Uint32Array(64 * 64);
      let at = 0;
      for (let a = 0; a < 64; a += 1) {
        for (let b = 0; b < 64; b += 1) {
          const x = axis === 0 ? 32 : a;
          const y = axis === 1 ? 32 : (axis === 0 ? a : b);
          const z = axis === 2 ? 32 : b;
          values[at++] = cube[x * 4096 + y * 64 + z];
        }
      }
      tensors.push({ name: `slice_s${shell}_${plane}`, shape: [64, 64], values });
    }
  }
  tensors.push({ name: "star_time", shape: [starField.stars.length], values: starField.stars.map((star) => star.time) });
  tensors.push({ name: "star_shell", shape: [starField.stars.length], values: starField.stars.map((star) => star.shell) });
  tensors.push({ name: "star_grad", shape: [starField.stars.length], values: starField.stars.map((star) => star.gradient) });
  tensors.push({
    name: "star_cesp",
    shape: [starField.stars.length, 3],
    values: starField.stars.flatMap((star) => [star.x, star.y, star.z])
  });
  return tensors;
}

function buildGguf(starField) {
  const tensors = tensorData(starField);
  const metadata = [
    ["general.architecture", 8, "asolaria-stars-shells"],
    ["general.name", 8, "ASOLARIA-STARS-SHELLS"],
    ["asolaria.axes", 8, "time, colour, energy, space"],
    ["asolaria.star", 8, "a star is a record: time=position in stream, colour=r, energy=g, space=b; gradiated colour = local change, not flat value"],
    ["asolaria.shell_law", 8, "VIII.A.7 photon law: shell = log3(tie count), counted never computed; more energy in, the further out the shell"],
    ["asolaria.tau", 4, 2],
    ["asolaria.stars", 4, starField.stars.length],
    ["asolaria.shells", 4, starField.cubes.length],
    ["asolaria.rings", 4, 2],
    ["asolaria.seed", 8, "live self-emission, emitted not read"]
  ];
  const meta = new Writer();
  for (const [key, type, value] of metadata) {
    meta.string(key);
    meta.u32(type);
    if (type === 8) meta.string(value);
    else meta.u32(value);
  }
  const dataParts = [];
  const tensorInfo = new Writer();
  let dataLength = 0;
  for (const tensor of tensors) {
    const padding = (32 - (dataLength % 32)) % 32;
    if (padding) dataParts.push(new Uint8Array(padding));
    dataLength += padding;
    tensorInfo.string(tensor.name);
    tensorInfo.u32(tensor.shape.length);
    for (const dimension of tensor.shape) tensorInfo.u64(dimension);
    tensorInfo.u32(0);
    tensorInfo.u64(dataLength);
    const bytes = new Uint8Array(tensor.values.length * 4);
    const view = new DataView(bytes.buffer);
    for (let index = 0; index < tensor.values.length; index += 1) view.setFloat32(index * 4, tensor.values[index], true);
    dataParts.push(bytes);
    dataLength += bytes.length;
  }
  const header = new Writer();
  header.u32(0x46554747);
  header.u32(3);
  header.u64(tensors.length);
  header.u64(metadata.length);
  header.raw(meta.finish());
  header.raw(tensorInfo.finish());
  const head = header.finish();
  const headPadding = (32 - (head.length % 32)) % 32;
  const output = new Uint8Array(head.length + headPadding + dataLength);
  output.set(head);
  let offset = head.length + headPadding;
  for (const part of dataParts) {
    output.set(part, offset);
    offset += part.length;
  }
  return output;
}

export async function generateArtifact(value) {
  const recipe = normalizeRecipe(value);
  const started = performance.now();
  const pumped = await pumpedSeed(recipe.seed, recipe.parameters.maxRounds);
  const output = buildGguf(buildStars(pumped.bytes));
  const outputSha256 = await sha256(output);
  const seedSha256 = await sha256(recipe.seed);
  const receipt = {
    schema: ARTIFACT_RECEIPT_SCHEMA,
    generator: recipe.generator,
    generatorVersion: recipe.generatorVersion,
    engine: recipe.engine,
    seedBytes: recipe.seed.byteLength,
    seedSha256,
    parameters: recipe.parameters,
    rounds: pumped.rounds,
    outputBytes: output.byteLength,
    outputSha256,
    durationMs: Math.round((performance.now() - started) * 100) / 100,
    verified: true
  };
  return { output, receipt, projection: recipeProjection(receipt) };
}
