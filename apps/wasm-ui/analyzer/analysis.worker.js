import { getAnalyzer } from './log-analyzer.js'

self.addEventListener('message', async (event) => {
  const payload = event.data || {}
  if (payload.type !== 'analyze') return

  const lines = Array.isArray(payload.lines) ? payload.lines : []
  const channel = typeof payload.channel === 'string' ? payload.channel : 'runtime'
  const preferWasm = payload.preferWasm !== false

  try {
    const analyzer = await getAnalyzer(lines, { preferWasm, channel })
    const events = analyzer.normalizeLines(lines, channel)
    const heatmap = analyzer.aggregateHeatmap(events)

    self.postMessage({
      ok: true,
      analyzer: analyzer.name,
      events,
      heatmap,
    })
  } catch (error) {
    self.postMessage({
      ok: false,
      error: error instanceof Error ? error.message : String(error),
    })
  }
})
