function parseLineTimestamp(line) {
  const match = line.match(/^\[?(\d{4}-\d{2}-\d{2}[T\s]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)\]?/)
  if (!match) return new Date().toISOString()
  const raw = match[1].replace(' ', 'T')
  return raw.endsWith('Z') ? raw : `${raw}Z`
}

function inferSeverity(line) {
  if (/\b(error|fatal|panic|critical|traceback|exception)\b/i.test(line)) {
    return 'error'
  }
  if (/\b(warn|warning|forbidden|denied|429)\b/i.test(line)) {
    return 'warning'
  }
  return 'info'
}

export function normalizeLines(lines, channel = 'runtime') {
  return lines.map((line, index) => ({
    id: `js-${index}-${Math.random().toString(16).slice(2, 7)}`,
    channel,
    ts: parseLineTimestamp(line),
    severity: inferSeverity(line),
    message: line,
  }))
}

export function aggregateHeatmap(events) {
  const buckets = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    count: 0,
    warning: 0,
    error: 0,
  }))

  for (const event of events) {
    const date = new Date(event.ts)
    const hour = Number.isFinite(date.getTime()) ? date.getUTCHours() : 0
    const bucket = buckets[hour]
    bucket.count += 1
    if (event.severity === 'warning') bucket.warning += 1
    if (event.severity === 'error') bucket.error += 1
  }

  return buckets
}

export function computeGraphLayout(nodes, edges) {
  const radius = 180
  const centerX = 220
  const centerY = 220
  const positioned = nodes.map((node, index) => {
    const angle = (2 * Math.PI * index) / Math.max(nodes.length, 1)
    return {
      ...node,
      x: centerX + radius * Math.cos(angle),
      y: centerY + radius * Math.sin(angle),
    }
  })

  return {
    nodes: positioned,
    edges,
  }
}

export function createJsAnalyzer() {
  return {
    name: 'javascript-fallback',
    normalizeLines,
    aggregateHeatmap,
    computeGraphLayout,
  }
}
