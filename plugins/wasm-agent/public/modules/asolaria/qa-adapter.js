import { scoreBinaryCalibration } from "./calibration.js";
import { makeAsolariaReceipt } from "./runtime.js";

export const ASOLARIA_QA_SCHEMA = "hermes.wasm_agent.asolaria.qa_evaluation.v1";
export const ASOLARIA_QA_EXTRACTOR = "receipt-byte-0-lsb-v1";

function expectedBinary(value, id) {
  if (value === true || value === 1 || value === "1") return 1;
  if (value === false || value === 0 || value === "0") return 0;
  throw new TypeError(`expected must be binary for ${id}`);
}

function normalizeCases(cases) {
  if (!Array.isArray(cases) || !cases.length) {
    throw new TypeError("ASOLARIA QA evaluation requires cases");
  }
  const ids = new Set();
  return cases.map((item, index) => {
    const id = String(item?.id || `qa-${index + 1}`);
    if (ids.has(id)) throw new TypeError(`duplicate QA id: ${id}`);
    ids.add(id);
    const question = String(item?.question || "").trim();
    if (!question) throw new TypeError(`question is required for ${id}`);
    const split = String(item?.split || "holdout").toLowerCase();
    if (!["train", "holdout"].includes(split)) {
      throw new TypeError(`invalid split for ${id}: ${split}`);
    }
    return {
      id,
      topic: String(item?.topic || "default"),
      split,
      question,
      expected: expectedBinary(item?.expected, id)
    };
  });
}

export function predictionFromReceipt(receipt) {
  const bytes = receipt?.bytes;
  if (!(bytes instanceof Uint8Array) || !bytes.length) {
    throw new TypeError("ASOLARIA receipt bytes are required");
  }
  return bytes[0] & 1;
}

function majorityBaseline(train, holdout) {
  const trainPositive = train.filter((row) => row.expected === 1).length;
  const predicted = trainPositive > train.length / 2 ? 1 : 0;
  const correct = holdout.filter((row) => row.expected === predicted).length;
  return {
    prediction: predicted,
    correct,
    n: holdout.length,
    accuracy: correct / Math.max(1, holdout.length)
  };
}

export async function evaluateAsolariaBinaryQuestions(cases, options = {}) {
  const normalized = normalizeCases(cases);
  const receiptMaker = options.receiptMaker || makeAsolariaReceipt;
  if (typeof receiptMaker !== "function") throw new TypeError("receiptMaker must be a function");
  const rows = [];
  for (const item of normalized) {
    const receipt = await receiptMaker(
      new TextEncoder().encode(item.question),
      { name: `${item.id}.txt` }
    );
    rows.push({
      id: item.id,
      topic: item.topic,
      split: item.split,
      expected: item.expected,
      predicted: predictionFromReceipt(receipt)
    });
  }
  const calibration = scoreBinaryCalibration(rows, options);
  const train = rows.filter((row) => row.split === "train");
  const holdout = rows.filter((row) => row.split === "holdout");
  const majority = majorityBaseline(train, holdout);
  const invertedAccuracy = calibration.holdout.inverted.accuracy;
  const addsValue = calibration.decision.route === "invert-binary-output"
    && invertedAccuracy > majority.accuracy
    && invertedAccuracy > 0.5;
  return {
    schema: ASOLARIA_QA_SCHEMA,
    status: "measured",
    extractor: {
      id: ASOLARIA_QA_EXTRACTOR,
      predeclared: true,
      rule: "first receipt byte, least-significant bit"
    },
    sampleSize: rows.length,
    calibration,
    baselines: {
      majority,
      chance: { accuracy: 0.5 }
    },
    decision: {
      route: addsValue ? "invert-binary-output" : "no-added-value",
      authority: addsValue ? "calibrated-transform" : "none",
      addsValue,
      reason: addsValue
        ? "Sealed holdout inversion beats chance and the train-derived majority baseline."
        : "The predeclared ASOLARIA extractor does not beat the required holdout baselines."
    }
  };
}

export function arithmeticBinaryBenchmark(perTopicPerSplit = 60) {
  const count = Math.max(10, Math.min(200, Number(perTopicPerSplit) || 60));
  const cases = [];
  for (const split of ["train", "holdout"]) {
    const offset = split === "train" ? 0 : 1000;
    for (let index = 0; index < count; index += 1) {
      const parityValue = offset + index;
      cases.push({
        id: `${split}-parity-${index}`,
        split,
        topic: "parity",
        question: `Is ${parityValue} an even integer? Answer yes or no.`,
        expected: parityValue % 2 === 0
      });
      const comparisonTruth = index % 2 === 0;
      const left = offset + index + 20;
      const right = comparisonTruth ? left - 1 : left + 1;
      cases.push({
        id: `${split}-comparison-${index}`,
        split,
        topic: "comparison",
        question: `Is ${left} greater than ${right}? Answer yes or no.`,
        expected: comparisonTruth
      });
      const divisibleTruth = index % 2 === 0;
      const base = offset + index;
      const dividend = divisibleTruth ? base * 3 : base * 3 + 1;
      cases.push({
        id: `${split}-divisibility-${index}`,
        split,
        topic: "divisibility",
        question: `Is ${dividend} divisible by 3? Answer yes or no.`,
        expected: divisibleTruth
      });
    }
  }
  return cases;
}

export function qaEvaluationProjection(result) {
  const holdout = result.calibration.holdout;
  return [
    `s=${result.status}`,
    `x=${result.extractor.id}`,
    `n=${result.sampleSize}`,
    `h=${holdout.n}`,
    `direct=${holdout.direct.correct}/${holdout.n}`,
    `inverted=${holdout.inverted.correct}/${holdout.n}`,
    `majority=${result.baselines.majority.correct}/${holdout.n}`,
    `route=${result.decision.route}`,
    `authority=${result.decision.authority}`
  ].join("|");
}
