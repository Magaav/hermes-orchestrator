import {
  getCapabilities,
  getNodeLogs,
  getNodeStatus,
  listNodes,
  runNodeAction,
} from './api.js'

const state = {
  capabilities: null,
  nodes: [],
  selectedNode: null,
  selectedChannel: 'runtime',
  tail: 220,
  events: [],
  stream: null,
  reconnectTimer: null,
  worker: null,
  workerReady: false,
}

const elements = {
  featureBadge: document.getElementById('featureBadge'),
  connectionBadge: document.getElementById('connectionBadge'),
  fleetError: document.getElementById('fleetError'),
  nodesList: document.getElementById('nodesList'),
  refreshNodesBtn: document.getElementById('refreshNodesBtn'),
  nodeTitle: document.getElementById('nodeTitle'),
  nodeMeta: document.getElementById('nodeMeta'),
  startActionBtn: document.getElementById('startActionBtn'),
  stopActionBtn: document.getElementById('stopActionBtn'),
  restartActionBtn: document.getElementById('restartActionBtn'),
  logOutput: document.getElementById('logOutput'),
  reloadLogsBtn: document.getElementById('reloadLogsBtn'),
  tailInput: document.getElementById('tailInput'),
  logChannelTabs: document.getElementById('logChannelTabs'),
  analyzerName: document.getElementById('analyzerName'),
  eventCount: document.getElementById('eventCount'),
  warnCount: document.getElementById('warnCount'),
  errorCount: document.getElementById('errorCount'),
  heatmap: document.getElementById('heatmap'),
  toastRack: document.getElementById('toastRack'),
}

const actionButtons = [
  elements.startActionBtn,
  elements.stopActionBtn,
  elements.restartActionBtn,
]

function escapeHtml(text) {
  return String(text)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;')
}

function setFeatureBadge(text, muted = false) {
  elements.featureBadge.textContent = text
  elements.featureBadge.classList.toggle('muted', muted)
}

function setConnectionBadge(text, muted = false) {
  elements.connectionBadge.textContent = text
  elements.connectionBadge.classList.toggle('muted', muted)
}

function showFleetError(message) {
  if (!message) {
    elements.fleetError.classList.add('hidden')
    elements.fleetError.textContent = ''
    return
  }
  elements.fleetError.classList.remove('hidden')
  elements.fleetError.textContent = message
}

function toast(message, type = 'success') {
  const item = document.createElement('div')
  item.className = `toast ${type === 'error' ? 'error' : 'success'}`
  item.textContent = message
  elements.toastRack.appendChild(item)
  setTimeout(() => {
    item.remove()
  }, 4200)
}

function formatTs(ts) {
  if (!ts) return '--'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return String(ts)
  return date.toLocaleString()
}

function summarizeNode(node) {
  const runtime = node.runtime_type || 'unknown'
  const mode = node.state_mode || 'unknown'
  const alertCount = Number(node.attention_events_last_200 || 0)
  return `${runtime} | ${mode} | alerts:${alertCount}`
}

function renderNodes() {
  elements.nodesList.innerHTML = ''

  if (!state.nodes.length) {
    const empty = document.createElement('div')
    empty.className = 'node-meta'
    empty.textContent = 'No nodes discovered yet.'
    elements.nodesList.appendChild(empty)
    return
  }

  for (const node of state.nodes) {
    const card = document.createElement('button')
    card.type = 'button'
    card.className = 'node-card'
    if (node.node === state.selectedNode) {
      card.classList.add('is-selected')
    }

    const statusClass = node.running ? 'running' : 'idle'
    card.innerHTML = `
      <div class="node-row">
        <span class="node-name">${escapeHtml(node.node)}</span>
        <span class="node-status ${statusClass}">${escapeHtml(node.status || 'unknown')}</span>
      </div>
      <div class="node-meta">${escapeHtml(summarizeNode(node))}</div>
    `

    card.addEventListener('click', () => {
      selectNode(node.node)
    })

    elements.nodesList.appendChild(card)
  }
}

async function selectNode(node) {
  if (!node) return
  await loadNodeDetail(node)
}

function setActionButtonsEnabled(enabled) {
  for (const button of actionButtons) {
    button.disabled = !enabled
  }
}

function renderNodeMeta(statusPayload) {
  const status = statusPayload || {}
  const lines = [
    `running: ${Boolean(status.running)}`,
    `status: ${status.status || 'unknown'}`,
    `runtime_type: ${status.runtime_type || 'unknown'}`,
    `state_mode: ${status.state_mode || 'unknown'}`,
    `state_code: ${typeof status.state_code === 'number' ? status.state_code : 'n/a'}`,
    `required_mounts_ok: ${
      typeof status.required_mounts_ok === 'boolean'
        ? String(status.required_mounts_ok)
        : 'n/a'
    }`,
    `env_path: ${status.env_path || 'n/a'}`,
    `clone_root: ${status.clone_root || 'n/a'}`,
  ]
  elements.nodeMeta.classList.remove('empty')
  elements.nodeMeta.textContent = lines.join('\n')
}

function renderLogLines(events) {
  if (!events.length) {
    elements.logOutput.innerHTML = '<div class="log-line">No log lines in selected window.</div>'
    return
  }

  const rows = events.map((event) => {
    const ts = escapeHtml(formatTs(event.ts))
    const sev = String(event.severity || 'info').toLowerCase()
    const message = escapeHtml(event.message || '')
    return `<div class="log-line ${sev}">[${ts}] [${escapeHtml(sev)}] ${message}</div>`
  })

  elements.logOutput.innerHTML = rows.join('')
  elements.logOutput.scrollTop = elements.logOutput.scrollHeight
}

function renderHeatmap(buckets) {
  elements.heatmap.innerHTML = ''
  const values = Array.isArray(buckets) ? buckets : []
  const maxCount = Math.max(1, ...values.map((item) => Number(item.count || 0)))

  for (let hour = 0; hour < 24; hour += 1) {
    const bucket = values.find((item) => Number(item.hour) === hour) || {
      count: 0,
      warning: 0,
      error: 0,
    }
    const count = Number(bucket.count || 0)
    const alpha = 0.12 + (count / maxCount) * 0.88

    const cell = document.createElement('div')
    cell.className = 'heat-cell'
    cell.style.background = `rgba(58, 209, 198, ${alpha.toFixed(3)})`
    cell.title = `${String(hour).padStart(2, '0')}:00 count=${count} warning=${Number(
      bucket.warning || 0,
    )} error=${Number(bucket.error || 0)}`
    elements.heatmap.appendChild(cell)
  }
}

function aggregateHeatmapFallback(events) {
  const buckets = Array.from({ length: 24 }, (_, hour) => ({
    hour,
    count: 0,
    warning: 0,
    error: 0,
  }))

  for (const event of events) {
    const date = new Date(event.ts)
    const hour = Number.isNaN(date.getTime()) ? 0 : date.getUTCHours()
    const bucket = buckets[hour]
    bucket.count += 1
    if (event.severity === 'warning') bucket.warning += 1
    if (event.severity === 'error') bucket.error += 1
  }

  return buckets
}

function updateAnalysisFromEvents(events) {
  const warningCount = events.filter((event) => event.severity === 'warning').length
  const errorCount = events.filter((event) => event.severity === 'error').length

  elements.analyzerName.textContent = 'gateway-normalized'
  elements.eventCount.textContent = String(events.length)
  elements.warnCount.textContent = String(warningCount)
  elements.errorCount.textContent = String(errorCount)
  renderHeatmap(aggregateHeatmapFallback(events))
}

function triggerAnalysis(events) {
  if (!state.workerReady || !state.worker) {
    updateAnalysisFromEvents(events)
    return
  }

  const lines = events.map((event) => String(event.raw || event.message || ''))
  state.worker.postMessage({
    type: 'analyze',
    lines,
    channel: state.selectedChannel,
    preferWasm: Boolean(state.capabilities?.enhanced?.wasm_runtime_switch),
  })
}

function setSelectedChannel(channel) {
  state.selectedChannel = channel

  const tabs = elements.logChannelTabs.querySelectorAll('[data-channel]')
  for (const tab of tabs) {
    const selected = tab.getAttribute('data-channel') === channel
    tab.classList.toggle('is-active', selected)
  }
}

function upsertNodeSummary(statusEvent) {
  if (!statusEvent || !statusEvent.node) return

  const index = state.nodes.findIndex((node) => node.node === statusEvent.node)
  if (index === -1) return

  const previous = state.nodes[index]
  state.nodes[index] = {
    ...previous,
    running: Boolean(statusEvent.running),
    status: statusEvent.status || previous.status,
    runtime_type: statusEvent.runtime_type || previous.runtime_type,
    state_mode: statusEvent.state_mode || previous.state_mode,
  }
}

async function refreshNodes() {
  try {
    showFleetError('')
    const payload = await listNodes()
    state.nodes = Array.isArray(payload.nodes) ? payload.nodes : []

    if (!state.selectedNode && state.nodes.length) {
      state.selectedNode = state.nodes[0].node
    }

    if (state.selectedNode && !state.nodes.some((node) => node.node === state.selectedNode)) {
      state.selectedNode = state.nodes.length ? state.nodes[0].node : null
    }

    renderNodes()

    if (state.selectedNode) {
      await loadNodeDetail(state.selectedNode)
    } else {
      elements.nodeMeta.textContent = 'Select a node to inspect status and logs.'
      elements.nodeMeta.classList.add('empty')
      setActionButtonsEnabled(false)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    showFleetError(message)
    setActionButtonsEnabled(false)
  }
}

async function loadNodeDetail(node) {
  state.selectedNode = node
  elements.nodeTitle.textContent = `Node Detail · ${node}`
  renderNodes()

  try {
    const [statusPayload, logsPayload] = await Promise.all([
      getNodeStatus(node),
      getNodeLogs(node, state.selectedChannel, state.tail),
    ])

    renderNodeMeta(statusPayload.status)

    state.events = Array.isArray(logsPayload.events) ? logsPayload.events : []
    renderLogLines(state.events)
    triggerAnalysis(state.events)

    setActionButtonsEnabled(Boolean(state.capabilities?.core?.safe_actions))
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed loading node data: ${message}`, 'error')
  }
}

async function reloadLogs() {
  if (!state.selectedNode) return

  try {
    const payload = await getNodeLogs(state.selectedNode, state.selectedChannel, state.tail)
    state.events = Array.isArray(payload.events) ? payload.events : []
    renderLogLines(state.events)
    triggerAnalysis(state.events)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed loading logs: ${message}`, 'error')
  }
}

function bindTabs() {
  const tabs = elements.logChannelTabs.querySelectorAll('[data-channel]')
  for (const tab of tabs) {
    tab.addEventListener('click', async () => {
      const channel = tab.getAttribute('data-channel') || 'runtime'
      setSelectedChannel(channel)
      await reloadLogs()
    })
  }
}

function lockActionButtons(locked) {
  for (const button of actionButtons) {
    button.disabled = locked
  }
}

async function performAction(action) {
  const node = state.selectedNode
  if (!node) {
    toast('Select a node before running actions.', 'error')
    return
  }

  if (!state.capabilities?.core?.safe_actions?.includes(action)) {
    toast(`Action '${action}' is not enabled by fleet capabilities.`, 'error')
    return
  }

  try {
    const statusPayload = await getNodeStatus(node)
    const running = Boolean(statusPayload.status?.running)
    const status = statusPayload.status?.status || 'unknown'
    const confirmed = window.confirm(
      `Confirm ${action} on ${node}?\nFresh status: ${status} (running=${running})\n\nThis maps directly to clone_manager.py and is audited.`,
    )

    if (!confirmed) {
      return
    }

    lockActionButtons(true)
    const payload = await runNodeAction(node, action)
    const result = payload.result || {}
    const before = result.before?.status || 'unknown'
    const after = result.after?.status || 'unknown'

    toast(`${action} accepted for ${node} (${before} -> ${after})`, 'success')

    await refreshNodes()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Action failed: ${message}`, 'error')
  } finally {
    lockActionButtons(false)
  }
}

function handleSseLogEvent(data) {
  if (!data || data.node !== state.selectedNode) {
    return
  }
  if (data.channel !== state.selectedChannel) {
    return
  }

  state.events.push(data)
  if (state.events.length > state.tail) {
    state.events = state.events.slice(-state.tail)
  }

  renderLogLines(state.events)
  triggerAnalysis(state.events)
}

function connectStream() {
  if (!state.capabilities?.core?.sse) {
    setConnectionBadge('Stream unavailable', true)
    return
  }

  if (state.stream) {
    state.stream.close()
    state.stream = null
  }

  setConnectionBadge('Connecting stream...', true)

  const token = window.localStorage.getItem('wasm_ui_api_token') || ''
  const streamUrl = token
    ? `/api/fleet/stream?token=${encodeURIComponent(token)}`
    : '/api/fleet/stream'
  const stream = new EventSource(streamUrl)
  state.stream = stream

  stream.addEventListener('connected', () => {
    setConnectionBadge('Stream connected')
  })

  stream.addEventListener('heartbeat', () => {
    setConnectionBadge('Stream live')
  })

  stream.addEventListener('status', (event) => {
    const data = JSON.parse(event.data)
    upsertNodeSummary(data)
    renderNodes()

    if (data.node === state.selectedNode) {
      const runtime = data.runtime_type || 'unknown'
      const mode = data.state_mode || 'unknown'
      const hint = `running: ${Boolean(data.running)}\nstatus: ${data.status || 'unknown'}\nruntime_type: ${runtime}\nstate_mode: ${mode}`
      elements.nodeMeta.classList.remove('empty')
      elements.nodeMeta.textContent = hint
    }
  })

  stream.addEventListener('log', (event) => {
    handleSseLogEvent(JSON.parse(event.data))
  })

  stream.addEventListener('action', (event) => {
    const data = JSON.parse(event.data)
    const node = data.request?.node || 'node'
    const action = data.request?.action || 'action'
    toast(`Audit: ${action} executed for ${node}.`, 'success')
  })

  stream.addEventListener('monitor', (event) => {
    const data = JSON.parse(event.data)
    if (data.state === 'error') {
      toast(`Monitor error: ${data.message || 'unknown'}`, 'error')
    }
  })

  stream.onerror = () => {
    setConnectionBadge('Stream reconnecting...', true)
    stream.close()
    if (state.reconnectTimer) {
      clearTimeout(state.reconnectTimer)
    }
    state.reconnectTimer = window.setTimeout(() => {
      connectStream()
    }, 2500)
  }
}

function initWorker() {
  if (typeof Worker === 'undefined') {
    updateAnalysisFromEvents(state.events)
    return
  }

  try {
    const worker = new Worker('/analyzer/analysis.worker.js', { type: 'module' })
    state.worker = worker
    state.workerReady = true

    worker.addEventListener('message', (event) => {
      const payload = event.data || {}
      if (!payload.ok) {
        state.workerReady = false
        elements.analyzerName.textContent = 'gateway-normalized'
        updateAnalysisFromEvents(state.events)
        return
      }

      const analyzedEvents = Array.isArray(payload.events) ? payload.events : []
      const warningCount = analyzedEvents.filter((item) => item.severity === 'warning').length
      const errorCount = analyzedEvents.filter((item) => item.severity === 'error').length

      elements.analyzerName.textContent = payload.analyzer || 'javascript-fallback'
      elements.eventCount.textContent = String(analyzedEvents.length)
      elements.warnCount.textContent = String(warningCount)
      elements.errorCount.textContent = String(errorCount)
      renderHeatmap(payload.heatmap)
    })
  } catch {
    state.workerReady = false
    updateAnalysisFromEvents(state.events)
  }
}

function bindInputs() {
  elements.refreshNodesBtn.addEventListener('click', async () => {
    await refreshNodes()
  })

  elements.reloadLogsBtn.addEventListener('click', async () => {
    await reloadLogs()
  })

  elements.tailInput.addEventListener('change', async () => {
    const parsed = Number.parseInt(elements.tailInput.value, 10)
    const next = Number.isNaN(parsed) ? 220 : parsed
    state.tail = Math.min(1500, Math.max(20, next))
    elements.tailInput.value = String(state.tail)
    await reloadLogs()
  })

  for (const button of actionButtons) {
    button.addEventListener('click', async () => {
      const action = button.getAttribute('data-action') || ''
      await performAction(action)
    })
  }

  bindTabs()
}

function maybePromptToken(capabilities) {
  const authRequired = Boolean(capabilities?.core?.auth_required)
  if (!authRequired) return

  const existing = window.localStorage.getItem('wasm_ui_api_token') || ''
  if (existing) return

  const token = window.prompt('This gateway requires a bearer token. Paste WASM_UI_API_TOKEN:')
  if (token && token.trim()) {
    window.localStorage.setItem('wasm_ui_api_token', token.trim())
  }
}

async function loadCapabilities() {
  const payload = await getCapabilities()
  state.capabilities = payload.capabilities || {}

  const exp = Boolean(state.capabilities.experimental_enabled)
  const mode = exp ? 'Experimental enabled' : 'Experimental disabled'
  setFeatureBadge(mode, !exp)

  maybePromptToken(state.capabilities)

  if (!exp) {
    showFleetError('WASM UI routes are disabled. Set WASM_UI_EXPERIMENTAL=1 and refresh.')
    setActionButtonsEnabled(false)
  }
}

async function boot() {
  setActionButtonsEnabled(false)
  bindInputs()
  initWorker()

  try {
    await loadCapabilities()

    if (state.capabilities?.experimental_enabled) {
      await refreshNodes()
      connectStream()
    } else {
      setConnectionBadge('Stream disabled', true)
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    showFleetError(message)
    setConnectionBadge('Unavailable', true)
    toast(`Failed to initialize UI: ${message}`, 'error')
  }
}

boot()
