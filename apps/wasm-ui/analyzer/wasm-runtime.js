let wasmModulePromise = null

async function importWasmModule() {
  if (!wasmModulePromise) {
    wasmModulePromise = import('/wasm/pkg/log_worker.js').catch(() => null)
  }
  return wasmModulePromise
}

export async function loadWasmAnalyzer() {
  const module = await importWasmModule()
  if (!module) return null

  try {
    if (typeof module.default === 'function') {
      await module.default('/wasm/pkg/log_worker_bg.wasm')
    }

    if (typeof module.normalize_lines !== 'function') {
      return null
    }

    return {
      name: 'rust-wasm',
      normalizeLines(lines, channel = 'runtime') {
        const payload = module.normalize_lines(lines.join('\n'), channel)
        return JSON.parse(payload)
      },
      aggregateHeatmap(events) {
        const payload = module.aggregate_heatmap(JSON.stringify(events))
        return JSON.parse(payload)
      },
      computeGraphLayout(nodes, edges) {
        const payload = module.layout_graph(JSON.stringify(nodes), JSON.stringify(edges))
        return JSON.parse(payload)
      },
    }
  } catch {
    return null
  }
}
