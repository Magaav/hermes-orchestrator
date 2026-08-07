import assert from "node:assert/strict";
import fs from "node:fs/promises";
import vm from "node:vm";

const source = await fs.readFile(new URL("./calibration.js", import.meta.url), "utf8");
const module = new vm.SourceTextModule(source, {
  context: vm.createContext({}),
  identifier: "asolaria-calibration"
});
await module.link(() => {
  throw new Error("calibration module has no imports");
});
await module.evaluate();
const {
  calibrationProjection,
  runSealedBinaryCalibration,
  scoreBinaryCalibration
} = module.namespace;

function antiExpertRows(perSplit = 90) {
  const rows = [];
  for (const split of ["train", "holdout"]) {
    for (let index = 0; index < perSplit; index += 1) {
      const expected = index % 2;
      rows.push({
        id: `${split}-${index}`,
        split,
        topic: `topic-${Math.floor(index / 3) % 3}`,
        expected,
        predicted: index % 3 === 0 ? expected : 1 - expected
      });
    }
  }
  return rows;
}

const calibrated = scoreBinaryCalibration(antiExpertRows());
assert.equal(calibrated.train.direct.accuracy, 1 / 3);
assert.equal(calibrated.holdout.direct.accuracy, 1 / 3);
assert.equal(calibrated.holdout.inverted.accuracy, 2 / 3);
assert.equal(calibrated.decision.route, "invert-binary-output");
assert.equal(calibrated.decision.authority, "calibrated-transform");
assert.match(calibrationProjection(calibrated), /route=invert-binary-output/);

const chanceRows = antiExpertRows().map((row, index) => ({
  ...row,
  predicted: Math.floor(index / 2) % 2
}));
const chance = scoreBinaryCalibration(chanceRows);
assert.equal(chance.holdout.direct.accuracy, 0.5);
assert.equal(chance.decision.route, "hypothesis-only");

let leakedExpected = false;
const sealed = await runSealedBinaryCalibration(
  antiExpertRows(90).map((row) => ({ ...row, question: `Question ${row.id}` })),
  (visible) => {
    leakedExpected ||= Object.hasOwn(visible, "expected");
    const index = Number(visible.id.split("-").at(-1));
    const expectedForFixture = index % 2;
    return index % 3 === 0 ? expectedForFixture : 1 - expectedForFixture;
  }
);
assert.equal(leakedExpected, false, "predictor must not receive expected answers");
assert.equal(sealed.holdout.inverted.accuracy, 2 / 3);
assert.equal(sealed.decision.route, "invert-binary-output");

assert.throws(
  () => scoreBinaryCalibration([{ id: "x", expected: 2, predicted: 0 }]),
  /expected must be binary/
);
assert.throws(
  () => scoreBinaryCalibration([{ id: "x", expected: 0, predicted: 0, split: "train" }]),
  /holdout split/
);

console.log("asolaria calibration tests passed");
