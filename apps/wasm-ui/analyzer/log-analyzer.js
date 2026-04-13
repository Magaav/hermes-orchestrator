import { createJsAnalyzer } from './js-fallback.js'
import { loadWasmAnalyzer } from './wasm-runtime.js'

const MIN_BENCH_LINES = 1200
const BENCH_ITERATIONS = 3

let selectedAnalyzerPromise = null

function benchmarkNormalize(analyzer, lines, channel) {
  const start = performance.now()
  for (let i = 0; i < BENCH_ITERATIONS; i += 1) {
    analyzer.normalizeLines(lines, channel)
  }
  return performance.now() - start
}

async function chooseAnalyzer(lines, { preferWasm = true, channel = 'runtime' } = {}) {
  const jsAnalyzer = createJsAnalyzer()

  if (!preferWasm || !window.WebAssembly || lines.length < MIN_BENCH_LINES) {
    return jsAnalyzer
  }

  const wasmAnalyzer = await loadWasmAnalyzer()
  if (!wasmAnalyzer) {
    return jsAnalyzer
  }

  const sample = lines.slice(-Math.min(lines.length, 4000))
  const jsTime = benchmarkNormalize(jsAnalyzer, sample, channel)
  const wasmTime = benchmarkNormalize(wasmAnalyzer, sample, channel)

  // Require at least 15% improvement to switch to WASM.
  if (wasmTime <= jsTime * 0.85) {
    return wasmAnalyzer
  }

  return jsAnalyzer
}

export async function getAnalyzer(lines, options) {
  if (!selectedAnalyzerPromise) {
    selectedAnalyzerPromise = chooseAnalyzer(lines, options)
  }
  return selectedAnalyzerPromise
}

export function resetAnalyzerSelection() {
  selectedAnalyzerPromise = null
}
