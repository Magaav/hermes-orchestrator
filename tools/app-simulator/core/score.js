"use strict";

const { isoTimestamp } = require("./schema");

function scoreResult(result) {
  if (result.status === "pending") {
    result.score = null;
    result.finishedAt = result.finishedAt || isoTimestamp();
    return result;
  }

  const assertions = Array.isArray(result.assertions) ? result.assertions : [];
  const failedAssertions = assertions.filter((assertion) => assertion.status === "failed");
  const pendingAssertions = assertions.filter((assertion) => assertion.status === "pending");
  const passedAssertions = assertions.filter((assertion) => assertion.status === "passed");
  const hasErrors = Array.isArray(result.errors) && result.errors.length > 0;

  if (!assertions.length) {
    result.score = hasErrors ? 0 : 100;
  } else {
    result.score = Math.round((passedAssertions.length / assertions.length) * 100);
  }

  if (failedAssertions.length || hasErrors) {
    result.status = "failed";
  } else if (pendingAssertions.length) {
    result.status = "pending";
  } else {
    result.status = "passed";
  }
  result.finishedAt = result.finishedAt || isoTimestamp();
  return result;
}

module.exports = {
  scoreResult,
};
