export const ASOLARIA_LATTICE_SCHEMA = "hermes.wasm_agent.asolaria.lattice.v1";

const AXES = Object.freeze({
  time: Object.freeze(["past", "present", "future"]),
  colour: Object.freeze(["red", "green", "blue"]),
  energy: Object.freeze(["light", "dc", "ac"]),
  space: Object.freeze(["x", "y", "z"])
});

export function inspectAsolariaLattice() {
  const states = [];
  for (let time = 0; time < 3; time += 1) {
    for (let colour = 0; colour < 3; colour += 1) {
      for (let energy = 0; energy < 3; energy += 1) {
        for (let space = 0; space < 3; space += 1) {
          states.push({
            index: (((time * 3) + colour) * 3 + energy) * 3 + space,
            coordinates: [time, colour, energy, space],
            energy: AXES.energy[energy]
          });
        }
      }
    }
  }
  const ac = states.filter((state) => state.energy === "ac").length;
  const cells = [];
  for (let x = 0; x < 3; x += 1) {
    for (let y = 0; y < 3; y += 1) {
      for (let z = 0; z < 3; z += 1) {
        const coordinates = [x, y, z];
        const shell = coordinates.reduce((sum, value) => sum + Number(value !== 1), 0);
        cells.push({ coordinates, shell, partition: shell === 0 || shell === 3 ? "solid" : "translucent" });
      }
    }
  }
  const solid = cells.filter((cell) => cell.partition === "solid").length;
  const translucent = cells.length - solid;
  return {
    schema: ASOLARIA_LATTICE_SCHEMA,
    axes: AXES,
    states: states.length,
    centre: {
      coordinates: [1, 1, 1, 1],
      label: "present.green.dc.y",
      count: states.filter((state) => state.coordinates.every((value) => value === 1)).length
    },
    thirds: {
      ac: { states: ac, fraction: ac / states.length },
      spatialCells: cells.length,
      solid: { cells: solid, fraction: solid / cells.length },
      translucent: { cells: translucent, fraction: translucent / cells.length }
    }
  };
}

export function latticeProjection(result = inspectAsolariaLattice()) {
  return [
    `s=${result.states}`,
    `centre=${result.centre.count}`,
    `ac=${result.thirds.ac.states}`,
    `cells=${result.thirds.spatialCells}`,
    `solid=${result.thirds.solid.cells}`,
    `translucent=${result.thirds.translucent.cells}`
  ].join("|");
}
