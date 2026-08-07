export const ASOLARIA_CALIBRATION_SCHEMA = "hermes.wasm_agent.asolaria.calibration.v1";

const VALID_SPLITS = new Set(["train", "holdout"]);

function binary(value, field, id) {
  if (value === true || value === 1 || value === "1") return 1;
  if (value === false || value === 0 || value === "0") return 0;
  throw new TypeError(`${field} must be binary for ${id}`);
}

function normalizeRows(rows) {
  if (!Array.isArray(rows) || !rows.length) {
    throw new TypeError("ASOLARIA calibration requires at least one row");
  }
  const ids = new Set();
  return rows.map((row, index) => {
    const id = String(row?.id || `case-${index + 1}`);
    if (ids.has(id)) throw new TypeError(`duplicate calibration id: ${id}`);
    ids.add(id);
    const split = String(row?.split || "holdout").toLowerCase();
    if (!VALID_SPLITS.has(split)) throw new TypeError(`invalid split for ${id}: ${split}`);
    return {
      id,
      topic: String(row?.topic || "default"),
      split,
      expected: binary(row?.expected, "expected", id),
      predicted: binary(row?.predicted, "predicted", id)
    };
  });
}

function wilson(successes, total, z = 1.959963984540054) {
  if (!total) return { low: 0, high: 0 };
  const p = successes / total;
  const z2 = z * z;
  const denominator = 1 + z2 / total;
  const centre = (p + z2 / (2 * total)) / denominator;
  const margin = z * Math.sqrt((p * (1 - p) + z2 / (4 * total)) / total) / denominator;
  return {
    low: Math.max(0, centre - margin),
    high: Math.min(1, centre + margin)
  };
}

function metrics(rows) {
  const directCorrect = rows.reduce(
    (count, row) => count + Number(row.predicted === row.expected),
    0
  );
  const invertedCorrect = rows.length - directCorrect;
  return {
    n: rows.length,
    direct: {
      correct: directCorrect,
      accuracy: directCorrect / rows.length,
      interval95: wilson(directCorrect, rows.length)
    },
    inverted: {
      correct: invertedCorrect,
      accuracy: invertedCorrect / rows.length,
      interval95: wilson(invertedCorrect, rows.length)
    }
  };
}

function balanced(rows) {
  const positives = rows.filter((row) => row.expected === 1).length;
  const negatives = rows.length - positives;
  return {
    positives,
    negatives,
    ratio: Math.min(positives, negatives) / Math.max(1, rows.length),
    pass: positives > 0 && negatives > 0 && Math.abs(positives - negatives) <= 1
  };
}

function topicMetrics(rows) {
  const topics = new Map();
  for (const row of rows) {
    if (!topics.has(row.topic)) topics.set(row.topic, []);
    topics.get(row.topic).push(row);
  }
  return Object.fromEntries(
    [...topics.entries()].sort(([left], [right]) => left.localeCompare(right))
      .map(([topic, topicRows]) => [topic, metrics(topicRows)])
  );
}

function decision(train, holdout, holdoutBalance, topics, options) {
  const minimumHoldout = Math.max(1, Number(options.minimumHoldout || 30));
  const minimumTopicCases = Math.max(1, Number(options.minimumTopicCases || 10));
  const topicEntries = Object.values(topics);
  const topicStable = topicEntries.length > 0 && topicEntries.every(
    (topic) => topic.n >= minimumTopicCases && topic.inverted.accuracy > 0.5
  );
  const gates = {
    trainPresent: train.n > 0,
    holdoutMinimum: holdout.n >= minimumHoldout,
    holdoutBalanced: holdoutBalance.pass,
    directAntiCorrelated: holdout.direct.interval95.high < 0.5,
    invertedBeatsChance: holdout.inverted.interval95.low > 0.5,
    trainDirectionMatches: train.n > 0 && train.direct.accuracy < 0.5,
    topicStable
  };
  const invert = Object.values(gates).every(Boolean);
  return {
    route: invert ? "invert-binary-output" : "hypothesis-only",
    authority: invert ? "calibrated-transform" : "none",
    gates,
    reason: invert
      ? "Independent balanced holdout supports stable binary inversion."
      : "Anti-correlation is not independently strong and stable enough to route."
  };
}

export function scoreBinaryCalibration(rows, options = {}) {
  const normalized = normalizeRows(rows);
  const trainRows = normalized.filter((row) => row.split === "train");
  const holdoutRows = normalized.filter((row) => row.split === "holdout");
  if (!holdoutRows.length) throw new TypeError("ASOLARIA calibration requires a holdout split");
  const train = trainRows.length ? metrics(trainRows) : {
    n: 0,
    direct: { correct: 0, accuracy: 0, interval95: { low: 0, high: 0 } },
    inverted: { correct: 0, accuracy: 0, interval95: { low: 0, high: 0 } }
  };
  const holdout = metrics(holdoutRows);
  const topics = topicMetrics(holdoutRows);
  const holdoutBalance = balanced(holdoutRows);
  return {
    schema: ASOLARIA_CALIBRATION_SCHEMA,
    status: "measured",
    taskKind: "binary",
    sampleSize: normalized.length,
    train,
    holdout,
    holdoutBalance,
    topics,
    decision: decision(train, holdout, holdoutBalance, topics, options)
  };
}

export async function runSealedBinaryCalibration(cases, predictor, options = {}) {
  if (typeof predictor !== "function") throw new TypeError("predictor must be a function");
  if (!Array.isArray(cases)) throw new TypeError("cases must be an array");
  const rows = [];
  for (const [index, item] of cases.entries()) {
    const id = String(item?.id || `case-${index + 1}`);
    const visible = Object.freeze({
      id,
      question: String(item?.question || ""),
      topic: String(item?.topic || "default")
    });
    rows.push({
      id,
      topic: visible.topic,
      split: item?.split,
      expected: item?.expected,
      predicted: await predictor(visible)
    });
  }
  return scoreBinaryCalibration(rows, options);
}

export function calibrationProjection(result) {
  const holdout = result.holdout;
  return [
    `s=${result.status}`,
    `kind=${result.taskKind}`,
    `n=${result.sampleSize}`,
    `h=${holdout.n}`,
    `direct=${holdout.direct.correct}/${holdout.n}`,
    `inverted=${holdout.inverted.correct}/${holdout.n}`,
    `route=${result.decision.route}`,
    `authority=${result.decision.authority}`
  ].join("|");
}
