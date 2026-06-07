#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");

function fail(message, code = 2) {
  console.error(message);
  process.exit(code);
}

function resolveSimulatorPath() {
  const candidates = [
    path.join(__dirname, "app-simulator", "simulate.js"),
    path.join(__dirname, "..", "app-simulator", "simulate.js"),
  ];
  return candidates.find((candidate) => fs.existsSync(candidate)) || "";
}

const args = process.argv.slice(2);
if (args[0] !== "simulate") {
  fail("horc-local only supports: simulate <target> [options]");
}

const simulatorPath = resolveSimulatorPath();
if (!simulatorPath) {
  fail("horc-local could not find bundled app-simulator/simulate.js", 1);
}

process.argv = [process.argv[0], simulatorPath, ...args.slice(1)];
require(simulatorPath);
