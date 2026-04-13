#!/usr/bin/env node
import fs from 'node:fs/promises'
import path from 'node:path'
import { performance } from 'node:perf_hooks'
import process from 'node:process'
import { pathToFileURL } from 'node:url'

const ROOT = path.resolve(path.dirname(new URL(import.meta.url).pathname), '..')

function parseArg(flag, fallback = '') {
  const idx = process.argv.indexOf(flag)
  if (idx === -1 || idx + 1 >= process.argv.length) return fallback
  return process.argv[idx + 1]
}

function asInt(value, fallback) {
  const parsed = Number.parseInt(String(value), 10)
  return Number.isNaN(parsed) ? fallback : parsed
}

function benchmark(fn, iterations) {
  const start = performance.now()
  for (let i = 0; i < iterations; i += 1) {
    fn()
  }
  return performance.now() - start
}

function synthesizeLines(count) {
  const lines = []
  for (let i = 0; i < count; i += 1) {
    const minute = String(i % 60).padStart(2, '0')
    const second = String((i * 7) % 60).padStart(2, '0')
    const sev = i % 29 === 0 ? 'ERROR' : i % 11 === 0 ? 'WARNING' : 'INFO'
    lines.push(`[2026-04-11T15:${minute}:${second}Z] ${sev} sample event ${i}`)
  }
  return lines
}

async function loadLines(inputPath, targetCount) {
  if (!inputPath) {
    return synthesizeLines(targetCount)
  }

  const raw = await fs.readFile(inputPath, 'utf-8')
  const lines = raw.split(/\r?\n/).filter(Boolean)
  if (lines.length >= targetCount) {
    return lines.slice(0, targetCount)
  }

  const expanded = [...lines]
  while (expanded.length < targetCount) {
    expanded.push(...lines)
  }
  return expanded.slice(0, targetCount)
}

async function loadJsAnalyzer() {
  const mod = await import(pathToFileURL(path.join(ROOT, 'analyzer', 'js-fallback.js')).href)
  return mod.createJsAnalyzer()
}

async function loadWasmAnalyzer() {
  const pkgJs = path.join(ROOT, 'wasm', 'pkg', 'log_worker.js')
  const pkgWasm = path.join(ROOT, 'wasm', 'pkg', 'log_worker_bg.wasm')

  try {
    await fs.access(pkgJs)
    await fs.access(pkgWasm)
  } catch {
    return null
  }

  try {
    const mod = await import(pathToFileURL(pkgJs).href)
    if (typeof mod.default === 'function') {
      // Node's fetch does not reliably support file:// loading across versions.
      // Pass bytes directly for deterministic local/container benchmark runs.
      const wasmBytes = await fs.readFile(pkgWasm)
      await mod.default({ module_or_path: wasmBytes })
    }
    if (typeof mod.normalize_lines !== 'function') {
      return null
    }

    return {
      name: 'rust-wasm',
      normalizeLines(lines, channel) {
        return JSON.parse(mod.normalize_lines(lines.join('\n'), channel))
      },
    }
  } catch {
    return null
  }
}

async function main() {
  const inputPath = parseArg('--input', '')
  const linesCount = asInt(parseArg('--lines', '120000'), 120000)
  const iterations = asInt(parseArg('--iterations', '6'), 6)
  const channel = parseArg('--channel', 'runtime')

  const lines = await loadLines(inputPath, linesCount)
  const jsAnalyzer = await loadJsAnalyzer()
  const wasmAnalyzer = await loadWasmAnalyzer()

  const jsMs = benchmark(() => jsAnalyzer.normalizeLines(lines, channel), iterations)

  let wasmMs = null
  if (wasmAnalyzer) {
    wasmMs = benchmark(() => wasmAnalyzer.normalizeLines(lines, channel), iterations)
  }

  const jsPerIter = jsMs / iterations
  console.log(`bench lines=${lines.length} iterations=${iterations}`)
  console.log(`js total_ms=${jsMs.toFixed(2)} per_iter_ms=${jsPerIter.toFixed(2)}`)

  if (wasmMs == null) {
    console.log('wasm unavailable: build /apps/wasm-ui/wasm/pkg first')
    process.exit(0)
  }

  const wasmPerIter = wasmMs / iterations
  const improvement = ((jsPerIter - wasmPerIter) / jsPerIter) * 100

  console.log(`wasm total_ms=${wasmMs.toFixed(2)} per_iter_ms=${wasmPerIter.toFixed(2)}`)
  console.log(`improvement_percent=${improvement.toFixed(2)}`)

  if (improvement >= 15) {
    console.log('decision=use_wasm')
  } else {
    console.log('decision=stay_js_fallback')
  }
}

main().catch((error) => {
  const message = error instanceof Error ? error.message : String(error)
  console.error(`benchmark failed: ${message}`)
  process.exit(1)
})
