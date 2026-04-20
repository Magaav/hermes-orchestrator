import {
  getCapabilities,
  getGuardStatus,
  getNodeActivity,
  getNodeGuard,
  getNodeLogs,
  getNodeStatus,
  listNodes,
  runNodeAction,
} from './api.js'

const CHANNEL_LABELS = {
  runtime: 'Runtime',
  management: 'Management',
  attention: 'Attention',
  hermes_errors: 'Hermes Errors',
  hermes_gateway: 'Hermes Gateway',
  hermes_agent: 'Hermes Agent',
}

const TONE_CLASSES = ['tone-good', 'tone-watch', 'tone-critical', 'tone-neutral']
const GOOD_STATUSES = new Set(['running', 'healthy', 'ok'])
const ACTIVITY_LIMIT = 18

const state = {
  capabilities: null,
  nodes: [],
  nodeErrors: [],
  guardStatus: null,
  selectedNode: null,
  selectedChannel: 'runtime',
  tail: 220,
  events: [],
  stream: null,
  reconnectTimer: null,
  worker: null,
  workerReady: false,
  selectedStatus: null,
  selectedGuard: null,
  recentActivity: [],
  lastNodeRefreshAt: null,
  lastLogReloadAt: null,
  connectionLabel: 'Connecting stream...',
  connectionMuted: true,
  analyzerLabel: 'pending',
  actionLocked: false,
}

const elements = {
  featureBadge: document.getElementById('featureBadge'),
  connectionBadge: document.getElementById('connectionBadge'),
  fleetPostureCard: document.getElementById('fleetPostureCard'),
  fleetPostureValue: document.getElementById('fleetPostureValue'),
  fleetPostureMeta: document.getElementById('fleetPostureMeta'),
  fleetCoverageCard: document.getElementById('fleetCoverageCard'),
  fleetCoverageValue: document.getElementById('fleetCoverageValue'),
  fleetCoverageMeta: document.getElementById('fleetCoverageMeta'),
  fleetAttentionCard: document.getElementById('fleetAttentionCard'),
  fleetAttentionValue: document.getElementById('fleetAttentionValue'),
  fleetAttentionMeta: document.getElementById('fleetAttentionMeta'),
  guardStatusCard: document.getElementById('guardStatusCard'),
  guardStatusValue: document.getElementById('guardStatusValue'),
  guardStatusMeta: document.getElementById('guardStatusMeta'),
  opsModeCard: document.getElementById('opsModeCard'),
  opsModeValue: document.getElementById('opsModeValue'),
  opsModeMeta: document.getElementById('opsModeMeta'),
  fleetError: document.getElementById('fleetError'),
  nodesList: document.getElementById('nodesList'),
  refreshNodesBtn: document.getElementById('refreshNodesBtn'),
  nodeTitle: document.getElementById('nodeTitle'),
  nodeSummary: document.getElementById('nodeSummary'),
  nodeSignalStrip: document.getElementById('nodeSignalStrip'),
  nodeMetaGrid: document.getElementById('nodeMetaGrid'),
  statusFreshness: document.getElementById('statusFreshness'),
  incidentSummary: document.getElementById('incidentSummary'),
  incidentList: document.getElementById('incidentList'),
  doctorSummary: document.getElementById('doctorSummary'),
  doctorList: document.getElementById('doctorList'),
  activitySummary: document.getElementById('activitySummary'),
  activityTimeline: document.getElementById('activityTimeline'),
  startActionBtn: document.getElementById('startActionBtn'),
  stopActionBtn: document.getElementById('stopActionBtn'),
  restartActionBtn: document.getElementById('restartActionBtn'),
  reloadLogsBtn: document.getElementById('reloadLogsBtn'),
  tailInput: document.getElementById('tailInput'),
  logChannelTabs: document.getElementById('logChannelTabs'),
  analyzerName: document.getElementById('analyzerName'),
  eventCount: document.getElementById('eventCount'),
  warnCount: document.getElementById('warnCount'),
  errorCount: document.getElementById('errorCount'),
  analysisSummary: document.getElementById('analysisSummary'),
  logOutput: document.getElementById('logOutput'),
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

function pluralize(count, singular, plural = `${singular}s`) {
  return count === 1 ? singular : plural
}

function startCase(value) {
  const normalized = String(value || '').trim().replaceAll('_', ' ').replaceAll('-', ' ')
  if (!normalized) return 'Unknown'
  return normalized.replace(/\b\w/g, (char) => char.toUpperCase())
}

function truncateText(value, max = 160) {
  const text = String(value || '')
  if (text.length <= max) return text
  return `${text.slice(0, max - 1)}…`
}

function humanizeChannel(channel) {
  return CHANNEL_LABELS[channel] || startCase(channel)
}

function toneFromGuardDecision(decision) {
  const text = String(decision || '').toLowerCase()
  if (text === 'healthy') return 'good'
  if (text === 'restarted' || text === 'cooldown-active' || text === 'warned') return 'watch'
  if (text === 'skipped' || text === 'restart-failed' || text === 'retry-exhausted') return 'critical'
  return 'neutral'
}

function toneFromGuardStatus(guardStatus) {
  const effectiveStatus = String(guardStatus?.effective_status || guardStatus?.daemon_status || '').toLowerCase()
  const summary = guardStatus?.summary || {}
  if (effectiveStatus === 'running') {
    if (Number(summary.retry_exhausted_nodes || 0) > 0) return 'critical'
    if (Number(summary.warned_nodes || 0) > 0 || Number(summary.cooldown_nodes || 0) > 0) return 'watch'
    return 'good'
  }
  if (effectiveStatus === 'stale') return 'watch'
  if (effectiveStatus === 'error' || effectiveStatus === 'failed') return 'critical'
  return 'neutral'
}

function toneFromOutcome(outcome) {
  const text = String(outcome || '').toLowerCase()
  if (text === 'completed') return 'good'
  if (text === 'interrupted') return 'watch'
  if (text === 'errored') return 'critical'
  return 'neutral'
}

function toneFromSource(source) {
  const text = String(source || '').toLowerCase()
  if (text === 'human') return 'good'
  if (text === 'agent') return 'watch'
  return 'neutral'
}

function formatTs(ts) {
  if (!ts) return '--'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return String(ts)
  return date.toLocaleString()
}

function formatClock(ts) {
  if (!ts) return '--'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return String(ts)
  return date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shortenPath(path, parts = 3) {
  const value = String(path || '').trim()
  if (!value) return 'n/a'
  const segments = value.split('/').filter(Boolean)
  if (segments.length <= parts) return value
  return `.../${segments.slice(-parts).join('/')}`
}

function parseJson(value) {
  try {
    return JSON.parse(value)
  } catch {
    return {}
  }
}

function asArray(value) {
  return Array.isArray(value) ? value : []
}

function uniqueBy(items, keyFn) {
  const seen = new Set()
  const result = []
  for (const item of items) {
    const key = keyFn(item)
    if (seen.has(key)) continue
    seen.add(key)
    result.push(item)
  }
  return result
}

function setToneClass(element, tone = 'neutral') {
  if (!element) return
  for (const className of TONE_CLASSES) {
    element.classList.remove(className)
  }
  element.classList.add(`tone-${tone}`)
}

function signalChipHtml(text, tone = 'neutral') {
  const toneClass = tone === 'neutral' ? 'muted' : `tone-${tone}`
  return `<span class="signal-chip ${toneClass}">${escapeHtml(text)}</span>`
}

function metricCardHtml(title, headline, tone, rows) {
  const rowsHtml = rows
    .map((row) => {
      const titleAttr = row.title ? ` title="${escapeHtml(row.title)}"` : ''
      return `
        <div class="meta-row">
          <span>${escapeHtml(row.label)}</span>
          <strong${titleAttr}>${escapeHtml(row.value)}</strong>
        </div>
      `
    })
    .join('')

  return `
    <article class="meta-card tone-${tone}">
      <p class="meta-kicker">${escapeHtml(title)}</p>
      <h3>${escapeHtml(headline)}</h3>
      <div class="meta-rows">${rowsHtml}</div>
    </article>
  `
}

function incidentCardHtml(incident) {
  return `
    <article class="incident-item tone-${incident.tone}">
      <div class="incident-head">
        <strong>${escapeHtml(incident.title)}</strong>
        <span>${escapeHtml(incident.meta || '')}</span>
      </div>
      <p>${escapeHtml(incident.body)}</p>
    </article>
  `
}

function activityItemHtml(item) {
  const chips = [
    signalChipHtml(startCase(item.source), toneFromSource(item.source)),
    signalChipHtml(startCase(item.outcome), item.tone),
  ]

  if (item.toolCount > 0) {
    chips.push(signalChipHtml(`${item.toolCount} ${pluralize(item.toolCount, 'tool')}`, 'neutral'))
  }

  return `
    <article class="timeline-item tone-${item.tone}">
      <div class="timeline-dot tone-${item.tone}"></div>
      <div class="timeline-copy">
        <div class="timeline-head">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(formatClock(item.ts))}</span>
        </div>
        <p>${escapeHtml(item.description)}</p>
        <div class="timeline-meta-row">${chips.join('')}</div>
        ${item.detail ? `<div class="timeline-detail">${escapeHtml(item.detail)}</div>` : ''}
      </div>
    </article>
  `
}

function doctorCardHtml(item, focus = false) {
  const chips = [signalChipHtml(startCase(item.decision), item.tone)]

  if (item.action && item.action !== 'none') {
    chips.push(signalChipHtml(startCase(item.action), item.tone))
  }

  if (item.result && item.result !== 'none') {
    chips.push(signalChipHtml(startCase(item.result), item.tone))
  }

  if (item.retryCount > 0 || item.retryCeiling > 0) {
    chips.push(signalChipHtml(`retries ${item.retryCount}/${item.retryCeiling || '?'}`, 'neutral'))
  }

  if (item.cooldownUntil) {
    chips.push(signalChipHtml(`cooldown ${formatClock(item.cooldownUntil)}`, 'watch'))
  }

  return `
    <article class="doctor-item tone-${item.tone}${focus ? ' is-focus' : ''}">
      <div class="doctor-copy">
        <div class="doctor-head">
          <strong>${escapeHtml(item.title)}</strong>
          <span>${escapeHtml(formatClock(item.ts))}</span>
        </div>
        <div class="doctor-meta-row">${chips.join('')}</div>
        <p>${escapeHtml(item.description)}</p>
      </div>
    </article>
  `
}

function getSelectedNodeSummary() {
  return state.nodes.find((node) => node.node === state.selectedNode) || null
}

function getEffectiveSelectedStatus() {
  return state.selectedStatus || getSelectedNodeSummary()
}

function getGuardNodeState(nodeName = '') {
  const nodes = state.guardStatus?.nodes
  if (!nodes || !nodeName) return null
  return nodes[nodeName] || null
}

function getSelectedGuardSummary() {
  return state.selectedGuard?.summary || getGuardNodeState(state.selectedNode) || null
}

function normalizeActivityEntry(entry) {
  const source = String(entry?.interaction_source || 'system').toLowerCase()
  const outcome = String(entry?.cycle_outcome || 'completed').toLowerCase()
  const toolUsage = entry?.tool_usage || {}
  const toolCount = Number(toolUsage.tool_count || 0)
  const agentIdentity = String(entry?.agent_identity || entry?.node || state.selectedNode || 'Node cycle')
  const activityText =
    entry?.last_activity_desc ||
    entry?.summary_text ||
    entry?.response_preview ||
    entry?.message_preview ||
    'No activity summary captured.'
  const detailParts = []

  if (entry?.message_preview) {
    detailParts.push(`Input: ${entry.message_preview}`)
  }
  if (entry?.response_preview) {
    detailParts.push(`Reply: ${entry.response_preview}`)
  }

  return {
    key: entry?.id || `${entry?.ts || ''}|${agentIdentity}|${outcome}|${activityText}`,
    ts: entry?.ts || new Date().toISOString(),
    tone: toneFromOutcome(outcome),
    title: `${agentIdentity} · ${startCase(outcome)}`,
    description: truncateText(activityText, 180),
    detail: truncateText(detailParts.join(' · '), 220),
    source,
    outcome,
    toolCount,
  }
}

function setActivityEntries(entries) {
  const normalized = asArray(entries)
    .map((entry) => normalizeActivityEntry(entry))
    .sort((left, right) => String(right.ts || '').localeCompare(String(left.ts || '')))

  state.recentActivity = normalized.slice(0, ACTIVITY_LIMIT)
  renderActivityTimeline()
}

function getNodeRisk(node, statusOverride = null) {
  if (!node && !statusOverride) {
    return { score: 0, tone: 'neutral', label: 'Unknown' }
  }

  const status = statusOverride || {}
  const running =
    typeof status.running === 'boolean' ? status.running : Boolean(node?.running)
  const statusText = String(status.status || node?.status || 'unknown').toLowerCase()
  const attentionCount = Number(node?.attention_events_last_200 || 0)
  const requiredMountsOk = status.required_mounts_ok
  const stateMode = String(status.state_mode || node?.state_mode || '').toLowerCase()
  const nodeName = String(status.node || node?.node || state.selectedNode || '').trim()
  const guardDecision = String(getGuardNodeState(nodeName)?.decision || '').toLowerCase()

  let score = 0
  if (!running) score += 3
  if (statusText && !GOOD_STATUSES.has(statusText)) {
    score += statusText === 'unknown' ? 1 : 2
  }
  if (attentionCount >= 10) score += 3
  else if (attentionCount >= 4) score += 2
  else if (attentionCount > 0) score += 1
  if (requiredMountsOk === false) score += 3
  if (stateMode === 'invalid') score += 2
  if (guardDecision === 'retry-exhausted' || guardDecision === 'restart-failed') score += 3
  else if (guardDecision === 'skipped' || guardDecision === 'warned' || guardDecision === 'cooldown-active') score += 2
  else if (guardDecision === 'restarted') score += 1

  if (score >= 5) return { score, tone: 'critical', label: 'Critical' }
  if (score >= 2) return { score, tone: 'watch', label: 'Watch' }
  return { score, tone: 'good', label: 'Stable' }
}

function toneFromConnectionLabel(label) {
  const text = String(label || '').toLowerCase()
  if (text.includes('live') || text.includes('connected')) return 'good'
  if (text.includes('reconnecting') || text.includes('connecting')) return 'watch'
  if (text.includes('disabled') || text.includes('unavailable')) return 'critical'
  return 'neutral'
}

function compareNodes(left, right) {
  const riskDiff = getNodeRisk(right).score - getNodeRisk(left).score
  if (riskDiff) return riskDiff

  const attentionDiff =
    Number(right.attention_events_last_200 || 0) - Number(left.attention_events_last_200 || 0)
  if (attentionDiff) return attentionDiff

  if (Boolean(left.running) !== Boolean(right.running)) {
    return left.running ? -1 : 1
  }

  return String(left.node || '').localeCompare(String(right.node || ''))
}

function setFeatureBadge(text, muted = false) {
  elements.featureBadge.textContent = text
  elements.featureBadge.classList.toggle('muted', muted)
}

function setConnectionBadge(text, muted = false) {
  state.connectionLabel = text
  state.connectionMuted = muted
  elements.connectionBadge.textContent = text
  elements.connectionBadge.classList.toggle('muted', muted)
  renderFleetSummary()
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
  window.setTimeout(() => {
    item.remove()
  }, 4200)
}

function appendActivity(entry) {
  const item = normalizeActivityEntry(entry)

  if (entry?.node && state.selectedNode && entry.node !== state.selectedNode) {
    return
  }

  if (state.recentActivity.some((existing) => existing.key === item.key)) {
    return
  }

  state.recentActivity.unshift(item)
  state.recentActivity = state.recentActivity.slice(0, ACTIVITY_LIMIT)
  renderActivityTimeline()
}

function renderFleetSummary() {
  const total = state.nodes.length
  const runningCount = state.nodes.filter((node) => Boolean(node.running)).length
  const attentionNodes = state.nodes.filter((node) => getNodeRisk(node).tone !== 'good')
  const criticalNodes = state.nodes.filter((node) => getNodeRisk(node).tone === 'critical')

  let postureTone = 'neutral'
  let postureValue = 'Discovering...'
  let postureMeta = 'Waiting for fleet inventory.'

  if (total) {
    postureTone = criticalNodes.length ? 'critical' : attentionNodes.length ? 'watch' : 'good'
    postureValue = criticalNodes.length
      ? 'Immediate attention'
      : attentionNodes.length
        ? 'Watch list'
        : 'Healthy'
    postureMeta = criticalNodes.length
      ? `${criticalNodes.length} ${pluralize(criticalNodes.length, 'node')} need intervention now.`
      : attentionNodes.length
        ? `${attentionNodes.length} ${pluralize(attentionNodes.length, 'node')} should be reviewed.`
        : 'All discovered nodes look stable right now.'
  }

  setToneClass(elements.fleetPostureCard, postureTone)
  elements.fleetPostureValue.textContent = postureValue
  elements.fleetPostureMeta.textContent = postureMeta

  const coverageTone =
    total === 0 ? 'neutral' : runningCount === total ? 'good' : runningCount === 0 ? 'critical' : 'watch'
  setToneClass(elements.fleetCoverageCard, coverageTone)
  elements.fleetCoverageValue.textContent = `${runningCount} / ${total} active`
  elements.fleetCoverageMeta.textContent = total
    ? `${total - runningCount} ${pluralize(total - runningCount, 'node')} idle or unavailable.`
    : 'No running nodes reported yet.'

  const attentionTone =
    total === 0 ? 'neutral' : criticalNodes.length ? 'critical' : attentionNodes.length ? 'watch' : 'good'
  setToneClass(elements.fleetAttentionCard, attentionTone)
  elements.fleetAttentionValue.textContent = `${attentionNodes.length} ${pluralize(attentionNodes.length, 'node')}`
  elements.fleetAttentionMeta.textContent = state.nodeErrors.length
    ? `${state.nodeErrors.length} refresh ${pluralize(state.nodeErrors.length, 'error')} also need follow-up.`
    : attentionNodes.length
      ? 'Derived from live status, recent alerts, and guardrails.'
      : 'No active queue at the moment.'

  const opsTone = toneFromConnectionLabel(state.connectionLabel)
  const authLabel = state.capabilities?.core?.auth_required ? 'Auth required' : 'Local session'
  setToneClass(elements.opsModeCard, opsTone)
  elements.opsModeValue.textContent = state.connectionLabel
  elements.opsModeMeta.textContent = `${startCase(state.analyzerLabel)} analyzer · ${authLabel}`
}

function renderGuardSummary() {
  const guardStatus = state.guardStatus
  if (!guardStatus) {
    setToneClass(elements.guardStatusCard, 'neutral')
    elements.guardStatusValue.textContent = 'Checking...'
    elements.guardStatusMeta.textContent = 'Waiting for the latest doctor cycle.'
    return
  }

  const summary = guardStatus.summary || {}
  const tone = toneFromGuardStatus(guardStatus)
  const effectiveStatus = startCase(guardStatus.effective_status || guardStatus.daemon_status || 'unknown')
  const lastCycle = guardStatus.updated_at ? formatClock(guardStatus.updated_at) : '--'

  setToneClass(elements.guardStatusCard, tone)
  elements.guardStatusValue.textContent = effectiveStatus
  elements.guardStatusMeta.textContent =
    `Cycle ${lastCycle} · ${Number(summary.warned_nodes || 0)} warned · ` +
    `${Number(summary.remediated_nodes || 0)} remediated · ` +
    `${Number(summary.cooldown_nodes || 0) + Number(summary.retry_exhausted_nodes || 0)} constrained`
}

function renderNodes() {
  elements.nodesList.innerHTML = ''

  if (!state.nodes.length) {
    elements.nodesList.innerHTML = `
      <article class="empty-state">
        <strong>No nodes discovered yet.</strong>
        <p>Refresh the fleet once the gateway is available.</p>
      </article>
    `
    return
  }

  const sortedNodes = [...state.nodes].sort(compareNodes)

  for (const node of sortedNodes) {
    const risk = getNodeRisk(node)
    const alertCount = Number(node.attention_events_last_200 || 0)
    const guardDecision = String(getGuardNodeState(node.node)?.decision || '').trim()
    const card = document.createElement('button')
    card.type = 'button'
    card.className = `node-card tone-${risk.tone}`
    if (node.node === state.selectedNode) {
      card.classList.add('is-selected')
    }

    const alertTone = alertCount >= 4 ? 'critical' : alertCount > 0 ? 'watch' : 'neutral'
    card.innerHTML = `
      <div class="node-card-top">
        <div>
          <div class="node-title-row">
            <span class="node-name">${escapeHtml(node.node)}</span>
            <span class="node-priority tone-${risk.tone}">${escapeHtml(risk.label)}</span>
          </div>
          <p class="node-subline">
            ${escapeHtml(startCase(node.runtime_type || 'unknown'))} runtime ·
            ${escapeHtml(startCase(node.state_mode || 'unknown'))} mode
          </p>
        </div>
        <span class="node-status-pill tone-${node.running ? 'good' : 'critical'}">
          ${escapeHtml(node.status || 'unknown')}
        </span>
      </div>
      <div class="node-chip-row">
        ${signalChipHtml(node.running ? 'Running' : 'Stopped', node.running ? 'good' : 'critical')}
        ${signalChipHtml(`${alertCount} alerts / 200`, alertTone)}
        ${guardDecision ? signalChipHtml(`guard ${startCase(guardDecision)}`, toneFromGuardDecision(guardDecision)) : ''}
        ${
          node.state_code !== null && node.state_code !== undefined
            ? signalChipHtml(`state ${node.state_code}`, 'neutral')
            : ''
        }
      </div>
    `

    card.addEventListener('click', () => {
      selectNode(node.node)
    })

    elements.nodesList.appendChild(card)
  }
}

function renderNodeOverview() {
  const summary = getSelectedNodeSummary()
  const status = getEffectiveSelectedStatus()

  if (!state.selectedNode) {
    elements.nodeTitle.textContent = 'Node Detail'
    elements.nodeSummary.textContent = 'Select a node to inspect posture, incidents, and logs.'
    elements.nodeSignalStrip.innerHTML = signalChipHtml('Awaiting selection', 'neutral')
    updateActionButtons()
    return
  }

  if (!status) {
    elements.nodeTitle.textContent = `Node Detail · ${state.selectedNode}`
    elements.nodeSummary.textContent = 'Loading fresh status, incidents, and log context...'
    elements.nodeSignalStrip.innerHTML = signalChipHtml('Refreshing node context', 'neutral')
    updateActionButtons()
    return
  }

  const risk = getNodeRisk(summary, status)
  const alertCount = Number(summary?.attention_events_last_200 || 0)
  const guardSummary = getSelectedGuardSummary()
  const guardDecision = String(guardSummary?.decision || '').trim()
  const mountsTone =
    status.required_mounts_ok === false ? 'critical' : status.required_mounts_ok === true ? 'good' : 'neutral'

  elements.nodeTitle.textContent = `Node Detail · ${state.selectedNode}`
  elements.nodeSummary.textContent = `${status.running ? 'Running' : 'Stopped'} · ${startCase(
    status.runtime_type || 'unknown',
  )} runtime · ${startCase(status.state_mode || 'unknown')} mode`

  const chips = [
    signalChipHtml(`${risk.label} posture`, risk.tone),
    signalChipHtml(`status ${status.status || 'unknown'}`, risk.tone),
    signalChipHtml(`${alertCount} attention ${pluralize(alertCount, 'event')}`, alertCount ? (alertCount >= 4 ? 'critical' : 'watch') : 'neutral'),
    signalChipHtml(
      status.required_mounts_ok === false
        ? 'mounts missing'
        : status.required_mounts_ok === true
          ? 'mounts ok'
          : 'mounts unknown',
      mountsTone,
    ),
    guardDecision ? signalChipHtml(`guard ${startCase(guardDecision)}`, toneFromGuardDecision(guardDecision)) : '',
    signalChipHtml(`${humanizeChannel(state.selectedChannel)} channel`, 'neutral'),
    signalChipHtml(`tail ${state.tail}`, 'neutral'),
  ]

  elements.nodeSignalStrip.innerHTML = chips.join('')
  updateActionButtons()
}

function renderNodeMeta(status) {
  if (!state.selectedNode) {
    elements.nodeMetaGrid.innerHTML = `
      <article class="empty-state">
        <strong>No node selected.</strong>
        <p>Fresh status cards will appear here once you choose a node from the fleet list.</p>
      </article>
    `
    elements.statusFreshness.textContent = 'No node selected'
    setToneClass(elements.statusFreshness, 'neutral')
    return
  }

  if (!status) {
    elements.nodeMetaGrid.innerHTML = `
      <article class="empty-state">
        <strong>Refreshing node details.</strong>
        <p>The gateway is loading current status, safety checks, and log routing for this node.</p>
      </article>
    `
    elements.statusFreshness.textContent = 'Refreshing'
    setToneClass(elements.statusFreshness, 'neutral')
    return
  }

  const summary = getSelectedNodeSummary()
  const risk = getNodeRisk(summary, status)
  const guardSummary = getSelectedGuardSummary()
  const guardDecision = String(guardSummary?.decision || '').trim()
  const currentLogPath = status.logs?.[state.selectedChannel] || summary?.log_paths?.[state.selectedChannel] || ''
  const allowedActions = state.capabilities?.core?.safe_actions || []
  const safetyTone =
    status.required_mounts_ok === false ? 'critical' : status.required_mounts_ok === true ? 'good' : 'neutral'

  const cards = [
    metricCardHtml('Lifecycle', status.running ? 'Running' : 'Stopped', risk.tone, [
      { label: 'Status', value: status.status || 'unknown' },
      { label: 'State mode', value: startCase(status.state_mode || 'unknown') },
      {
        label: 'State code',
        value: status.state_code !== null && status.state_code !== undefined ? String(status.state_code) : 'n/a',
      },
    ]),
    metricCardHtml('Runtime', startCase(status.runtime_type || 'unknown'), status.running ? 'good' : 'watch', [
      { label: 'Active channel', value: humanizeChannel(state.selectedChannel) },
      { label: 'Tail window', value: `${state.tail} lines` },
      {
        label: 'Recent alerts',
        value: `${Number(summary?.attention_events_last_200 || 0)} in last 200 lines`,
      },
    ]),
    metricCardHtml(
      'Safety',
      status.required_mounts_ok === false ? 'Guardrail issue' : 'Guardrails intact',
      safetyTone,
      [
        {
          label: 'Required mounts',
          value:
            status.required_mounts_ok === false
              ? 'missing'
              : status.required_mounts_ok === true
                ? 'ok'
                : 'unknown',
        },
        {
          label: 'Safe actions',
          value: allowedActions.length ? allowedActions.join(', ') : 'none',
          title: allowedActions.join(', '),
        },
        {
          label: 'Guard',
          value: guardDecision ? startCase(guardDecision) : 'pending',
        },
      ],
    ),
    metricCardHtml('Paths', humanizeChannel(state.selectedChannel), 'neutral', [
      {
        label: 'Env path',
        value: shortenPath(status.env_path),
        title: status.env_path || 'n/a',
      },
      {
        label: 'Clone root',
        value: shortenPath(status.clone_root),
        title: status.clone_root || 'n/a',
      },
      {
        label: 'Log path',
        value: shortenPath(currentLogPath),
        title: currentLogPath || 'n/a',
      },
    ]),
  ]

  elements.nodeMetaGrid.innerHTML = cards.join('')
  elements.statusFreshness.textContent = state.lastNodeRefreshAt
    ? `Fresh ${formatClock(state.lastNodeRefreshAt)}`
    : 'Fresh now'
  setToneClass(elements.statusFreshness, risk.tone)
}

function collectIncidents() {
  if (!state.selectedNode) return []

  const summary = getSelectedNodeSummary()
  const status = getEffectiveSelectedStatus()
  const guardSummary = getSelectedGuardSummary()
  const incidents = []
  const attentionCount = Number(summary?.attention_events_last_200 || 0)
  const guardDecision = String(guardSummary?.decision || '').toLowerCase()

  if (guardDecision && guardDecision !== 'healthy') {
    const symptoms = asArray(guardSummary?.symptoms)
      .map((item) => startCase(item))
      .join(', ')
    incidents.push({
      tone: toneFromGuardDecision(guardDecision),
      title: `Guard marked this node ${startCase(guardDecision)}`,
      body:
        symptoms ||
        `Last guard result was ${startCase(guardSummary?.remediation_result || 'notify only')}.`,
      meta: guardSummary?.updated_at ? formatTs(guardSummary.updated_at) : 'Guard doctor',
    })
  }

  if (status?.running === false) {
    incidents.push({
      tone: 'critical',
      title: 'Node is offline',
      body: 'Safe operations are still available, but runtime work is currently unavailable.',
      meta: `Status ${status.status || 'unknown'}`,
    })
  }

  if (status?.required_mounts_ok === false) {
    incidents.push({
      tone: 'critical',
      title: 'Required mounts are missing',
      body: 'Filesystem prerequisites are not satisfied for this node, so operator review is needed before further action.',
      meta: 'Guardrail check',
    })
  }

  if (attentionCount > 0) {
    incidents.push({
      tone: attentionCount >= 5 ? 'critical' : 'watch',
      title: `${attentionCount} recent attention ${pluralize(attentionCount, 'event')}`,
      body: 'The fleet summary already saw warning or error activity in the recent attention window.',
      meta: 'Attention log window',
    })
  }

  const severeEvents = uniqueBy(
    [...state.events]
      .reverse()
      .filter((event) => {
        const severity = String(event.severity || '').toLowerCase()
        return severity === 'warning' || severity === 'error'
      }),
    (event) => `${event.channel}|${event.severity}|${event.message}`,
  )

  for (const event of severeEvents.slice(0, 4)) {
    const severity = String(event.severity || '').toLowerCase()
    incidents.push({
      tone: severity === 'error' ? 'critical' : 'watch',
      title: `${humanizeChannel(event.channel)} ${startCase(severity)}`,
      body: truncateText(event.message || event.raw || 'Signal received'),
      meta: formatTs(event.ts),
    })
  }

  return incidents.slice(0, 6)
}

function renderIncidents() {
  const incidents = collectIncidents()
  const critical = incidents.some((incident) => incident.tone === 'critical')

  if (!state.selectedNode) {
    elements.incidentSummary.textContent = 'Select a node'
    setToneClass(elements.incidentSummary, 'neutral')
    elements.incidentList.innerHTML = `
      <article class="empty-state">
        <strong>No node selected.</strong>
        <p>The UI will surface operator-facing issues here once a node is active.</p>
      </article>
    `
    return
  }

  if (!incidents.length) {
    elements.incidentSummary.textContent = '0 active issues'
    setToneClass(elements.incidentSummary, 'good')
    elements.incidentList.innerHTML = `
      <article class="empty-state tone-good">
        <strong>No active issues detected.</strong>
        <p>This node looks stable in the current window, so logs are acting as drill-down rather than triage.</p>
      </article>
    `
    return
  }

  elements.incidentSummary.textContent = `${incidents.length} active ${pluralize(incidents.length, 'issue')}`
  setToneClass(elements.incidentSummary, critical ? 'critical' : 'watch')
  elements.incidentList.innerHTML = incidents.map((incident) => incidentCardHtml(incident)).join('')
}

function renderDoctorPanel() {
  if (!state.selectedNode) {
    elements.doctorSummary.textContent = 'No node selected'
    setToneClass(elements.doctorSummary, 'neutral')
    elements.doctorList.innerHTML = `
      <article class="empty-state">
        <strong>No node selected.</strong>
        <p>Guard findings and remediation history will appear here once you choose a node.</p>
      </article>
    `
    return
  }

  const summary = getSelectedGuardSummary()
  const records = asArray(state.selectedGuard?.records)
    .slice()
    .sort((left, right) => String(right.ts || '').localeCompare(String(left.ts || '')))

  if (!summary && !records.length) {
    elements.doctorSummary.textContent = 'No guard data yet'
    setToneClass(elements.doctorSummary, state.guardStatus ? 'watch' : 'neutral')
    elements.doctorList.innerHTML = `
      <article class="empty-state">
        <strong>No doctor cycle recorded for this node yet.</strong>
        <p>Start the Guard daemon to populate remediation history and bounded repair decisions.</p>
      </article>
    `
    return
  }

  const focus = summary || records[0]
  const tone = toneFromGuardDecision(focus?.decision)
  const retryCeiling = Number(
    focus?.retry_ceiling || state.guardStatus?.config?.retry_ceiling || 0,
  )
  const focusSymptoms = asArray(focus?.symptoms)
    .map((item) => startCase(item))
    .join(', ')
  const cards = [
    doctorCardHtml(
      {
        tone,
        title: `${state.selectedNode} doctor posture`,
        ts: focus?.updated_at || focus?.ts,
        decision: focus?.decision || 'unknown',
        action: focus?.remediation_action || 'none',
        result: focus?.remediation_result || 'none',
        retryCount: Number(focus?.retry_count || 0),
        retryCeiling,
        cooldownUntil: focus?.cooldown_until || '',
        description:
          focusSymptoms ||
          `Last guard result: ${startCase(focus?.remediation_result || 'no recorded action')}.`,
      },
      true,
    ),
  ]

  const recentRecords = records.filter((record) => {
    return !(
      String(record.ts || '') === String(focus?.updated_at || focus?.ts || '') &&
      String(record.decision || '') === String(focus?.decision || '')
    )
  })

  for (const record of recentRecords.slice(0, 4)) {
    const symptoms = asArray(record.symptoms)
      .map((item) => startCase(item))
      .join(', ')
    cards.push(
      doctorCardHtml({
        tone: toneFromGuardDecision(record.decision),
        title: `${startCase(record.decision || 'unknown')} cycle`,
        ts: record.ts,
        decision: record.decision || 'unknown',
        action: record.remediation_action || 'none',
        result: record.remediation_result || 'none',
        retryCount: Number(record.retry_count || 0),
        retryCeiling: Number(record.retry_ceiling || retryCeiling),
        cooldownUntil: record.cooldown_until || '',
        description:
          symptoms ||
          `Recorded result: ${startCase(record.remediation_result || 'no remediation result')}.`,
      }),
    )
  }

  elements.doctorSummary.textContent = `${startCase(focus?.decision || 'unknown')} · ${formatClock(
    focus?.updated_at || focus?.ts,
  )}`
  setToneClass(elements.doctorSummary, tone)
  elements.doctorList.innerHTML = cards.join('')
}

function renderActivityTimeline() {
  if (!state.selectedNode) {
    elements.activitySummary.textContent = 'No node selected'
    setToneClass(elements.activitySummary, 'neutral')
    elements.activityTimeline.innerHTML = `
      <article class="empty-state">
        <strong>No node selected.</strong>
        <p>Per-cycle agent timelines will appear here once you choose a node from the fleet list.</p>
      </article>
    `
    return
  }

  if (!state.recentActivity.length) {
    elements.activitySummary.textContent = 'No cycles logged'
    setToneClass(elements.activitySummary, 'neutral')
    elements.activityTimeline.innerHTML = `
      <article class="empty-state">
        <strong>No interaction cycles recorded yet.</strong>
        <p>The activity timeline is fed by <code>/logs/nodes/activities/${escapeHtml(state.selectedNode)}.jsonl</code>.</p>
      </article>
    `
    return
  }

  const critical = state.recentActivity.some((entry) => entry.outcome === 'errored')
  const warning = state.recentActivity.some((entry) => entry.outcome === 'interrupted')
  elements.activitySummary.textContent = `${state.recentActivity.length} recent ${pluralize(state.recentActivity.length, 'cycle')}`
  setToneClass(elements.activitySummary, critical ? 'critical' : warning ? 'watch' : 'good')
  elements.activityTimeline.innerHTML = state.recentActivity.map((item) => activityItemHtml(item)).join('')
}

function renderLogLines(events) {
  if (!events.length) {
    elements.logOutput.innerHTML = `
      <div class="log-empty">
        No log lines in ${escapeHtml(humanizeChannel(state.selectedChannel))} for the selected window.
      </div>
    `
    return
  }

  const rows = events.map((event) => {
    const ts = escapeHtml(formatTs(event.ts))
    const severity = String(event.severity || 'info').toLowerCase()
    const message = escapeHtml(event.message || '')
    return `<div class="log-line ${severity}">[${ts}] [${escapeHtml(severity)}] ${message}</div>`
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
    const alpha = 0.14 + (count / maxCount) * 0.86

    const cell = document.createElement('div')
    cell.className = 'heat-cell'
    cell.style.background = `rgba(73, 214, 195, ${alpha.toFixed(3)})`
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

function renderAnalysisStats(analyzerName, events, heatmap) {
  const warningCount = events.filter((event) => event.severity === 'warning').length
  const errorCount = events.filter((event) => event.severity === 'error').length
  const tone = errorCount ? 'critical' : warningCount ? 'watch' : events.length ? 'good' : 'neutral'

  state.analyzerLabel = analyzerName || 'gateway-normalized'
  elements.analyzerName.textContent = state.analyzerLabel
  elements.eventCount.textContent = String(events.length)
  elements.warnCount.textContent = String(warningCount)
  elements.errorCount.textContent = String(errorCount)
  elements.analysisSummary.textContent = events.length
    ? `${humanizeChannel(state.selectedChannel)} · ${warningCount} warnings · ${errorCount} errors`
    : 'No events in current window'
  setToneClass(elements.analysisSummary, tone)
  renderHeatmap(heatmap)
  renderFleetSummary()
}

function updateAnalysisFromEvents(events) {
  renderAnalysisStats('gateway-normalized', events, aggregateHeatmapFallback(events))
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

  renderNodeOverview()
  renderNodeMeta(getEffectiveSelectedStatus())
}

function getActionAvailability(action) {
  const safeActions = state.capabilities?.core?.safe_actions || []

  if (state.actionLocked) {
    return { enabled: false, reason: 'Action already in progress.' }
  }
  if (!state.selectedNode) {
    return { enabled: false, reason: 'Select a node first.' }
  }
  if (!safeActions.includes(action)) {
    return { enabled: false, reason: 'Action not enabled by fleet capabilities.' }
  }

  const status = getEffectiveSelectedStatus()
  if (!status) {
    return { enabled: true, reason: '' }
  }

  if (action === 'start' && status.running) {
    return { enabled: false, reason: 'Node is already running.' }
  }
  if (action === 'stop' && !status.running) {
    return { enabled: false, reason: 'Node is already stopped.' }
  }
  if (action === 'restart' && !status.running) {
    return { enabled: false, reason: 'Start the node before restarting it.' }
  }

  return { enabled: true, reason: '' }
}

function updateActionButtons() {
  for (const button of actionButtons) {
    const action = button.getAttribute('data-action') || ''
    const availability = getActionAvailability(action)
    button.disabled = !availability.enabled
    button.title = availability.reason
  }
}

async function selectNode(node) {
  if (!node) return
  await loadNodeDetail(node)
}

async function refreshNodes() {
  try {
    showFleetError('')
    const payload = await listNodes()
    state.nodes = Array.isArray(payload.nodes) ? payload.nodes : []
    state.nodeErrors = Array.isArray(payload.errors) ? payload.errors : []
    state.lastNodeRefreshAt = new Date().toISOString()

    if (!state.selectedNode && state.nodes.length) {
      state.selectedNode = state.nodes[0].node
    }

    if (state.selectedNode && !state.nodes.some((node) => node.node === state.selectedNode)) {
      state.selectedNode = state.nodes.length ? state.nodes[0].node : null
      state.selectedStatus = null
      state.selectedGuard = null
      state.recentActivity = []
    }

    if (state.nodeErrors.length) {
      const names = state.nodeErrors.map((item) => item.node).slice(0, 4).join(', ')
      const suffix = state.nodeErrors.length > 4 ? ', ...' : ''
      showFleetError(
        `${state.nodeErrors.length} ${pluralize(state.nodeErrors.length, 'node')} could not be refreshed: ${names}${suffix}`,
      )
    }

    renderNodes()
    renderFleetSummary()

    if (state.selectedNode) {
      await loadNodeDetail(state.selectedNode)
      return
    }

    state.events = []
    renderNodeOverview()
    renderNodeMeta(null)
    renderIncidents()
    renderDoctorPanel()
    renderActivityTimeline()
    renderLogLines([])
    updateAnalysisFromEvents([])
    updateActionButtons()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    showFleetError(message)
    updateActionButtons()
  }
}

async function loadNodeDetail(node) {
  if (!node) return

  const switchingNode = node !== state.selectedNode
  state.selectedNode = node

  if (switchingNode) {
    state.selectedStatus = null
    state.selectedGuard = null
    state.recentActivity = []
    state.events = []
    renderNodes()
    renderNodeOverview()
    renderNodeMeta(null)
    renderIncidents()
    renderDoctorPanel()
    renderActivityTimeline()
    renderLogLines([])
    updateAnalysisFromEvents([])
  } else {
    renderNodes()
    renderNodeOverview()
  }

  try {
    const [statusPayload, logsPayload, guardPayload, activityPayload] = await Promise.all([
      getNodeStatus(node),
      getNodeLogs(node, state.selectedChannel, state.tail),
      getNodeGuard(node),
      getNodeActivity(node),
    ])

    state.selectedStatus = statusPayload.status || null
    state.selectedGuard = guardPayload.guard || null
    setActivityEntries(activityPayload.activity)
    state.lastNodeRefreshAt = new Date().toISOString()
    renderNodeOverview()
    renderNodeMeta(state.selectedStatus)
    renderDoctorPanel()

    state.events = Array.isArray(logsPayload.events) ? logsPayload.events : []
    state.lastLogReloadAt = new Date().toISOString()
    renderLogLines(state.events)
    renderIncidents()
    triggerAnalysis(state.events)
    updateActionButtons()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed loading node data: ${message}`, 'error')
  }
}

async function refreshGuardStatus() {
  try {
    const payload = await getGuardStatus()
    state.guardStatus = payload.guard || null
    renderGuardSummary()
    renderNodes()
    renderFleetSummary()
    renderNodeOverview()
    renderNodeMeta(getEffectiveSelectedStatus())
    renderIncidents()
    renderDoctorPanel()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed loading guard status: ${message}`, 'error')
  }
}

async function reloadLogs() {
  if (!state.selectedNode) return

  try {
    const payload = await getNodeLogs(state.selectedNode, state.selectedChannel, state.tail)
    state.events = Array.isArray(payload.events) ? payload.events : []
    state.lastLogReloadAt = new Date().toISOString()
    renderNodeOverview()
    renderNodeMeta(getEffectiveSelectedStatus())
    renderIncidents()
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
  state.actionLocked = locked
  updateActionButtons()
}

async function performAction(action) {
  const node = state.selectedNode
  const availability = getActionAvailability(action)

  if (!node) {
    toast('Select a node before running actions.', 'error')
    return
  }

  if (!availability.enabled) {
    toast(availability.reason, 'error')
    return
  }

  try {
    const statusPayload = await getNodeStatus(node)
    state.selectedStatus = statusPayload.status || state.selectedStatus
    renderNodeOverview()
    renderNodeMeta(getEffectiveSelectedStatus())
    renderIncidents()

    const running = Boolean(state.selectedStatus?.running)
    const status = state.selectedStatus?.status || 'unknown'
    const mode = state.selectedStatus?.state_mode || 'unknown'
    const confirmed = window.confirm(
      `Confirm ${action} on ${node}?\nCurrent posture: ${status} (running=${running}, mode=${mode})\n\nThis action is audited through clone_manager.py.`,
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

function upsertNodeSummary(statusEvent) {
  if (!statusEvent || !statusEvent.node) {
    return { changed: false, previous: null, next: null }
  }

  const index = state.nodes.findIndex((node) => node.node === statusEvent.node)
  if (index === -1) {
    const next = {
      node: statusEvent.node,
      running: Boolean(statusEvent.running),
      status: statusEvent.status || 'unknown',
      runtime_type: statusEvent.runtime_type || 'unknown',
      state_mode: statusEvent.state_mode || 'unknown',
      state_code: null,
      attention_events_last_200: 0,
      log_paths: {},
    }
    state.nodes.push(next)
    return { changed: true, previous: null, next, discovered: true }
  }

  const previous = state.nodes[index]
  const next = {
    ...previous,
    running: Boolean(statusEvent.running),
    status: statusEvent.status || previous.status,
    runtime_type: statusEvent.runtime_type || previous.runtime_type,
    state_mode: statusEvent.state_mode || previous.state_mode,
  }

  state.nodes[index] = next
  const changed =
    previous.running !== next.running ||
    previous.status !== next.status ||
    previous.runtime_type !== next.runtime_type ||
    previous.state_mode !== next.state_mode

  return { changed, previous, next, discovered: false }
}

function handleSseLogEvent(data) {
  if (data.node !== state.selectedNode || data.channel !== state.selectedChannel) {
    return
  }

  state.events.push(data)
  if (state.events.length > state.tail) {
    state.events = state.events.slice(-state.tail)
  }

  renderLogLines(state.events)
  renderIncidents()
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
    const data = parseJson(event.data)
    upsertNodeSummary(data)
    renderNodes()
    renderFleetSummary()

    if (data.node === state.selectedNode && state.selectedStatus) {
      state.selectedStatus = {
        ...state.selectedStatus,
        running: Boolean(data.running),
        status: data.status || state.selectedStatus.status,
        runtime_type: data.runtime_type || state.selectedStatus.runtime_type,
        state_mode: data.state_mode || state.selectedStatus.state_mode,
      }
      renderNodeOverview()
      renderNodeMeta(state.selectedStatus)
      renderIncidents()
    }
  })

  stream.addEventListener('log', (event) => {
    handleSseLogEvent(parseJson(event.data))
  })

  stream.addEventListener('action', (event) => {
    const data = parseJson(event.data)
    const node = data.request?.node || 'node'
    const action = data.request?.action || 'action'
    const before = data.before?.status || 'unknown'
    const after = data.after?.status || 'unknown'
    toast(`${startCase(action)} completed for ${node} (${before} -> ${after})`)
  })

  stream.addEventListener('monitor', (event) => {
    const data = parseJson(event.data)

    if (data.state === 'error') {
      toast(`Monitor error: ${data.message || 'unknown'}`, 'error')
    }
  })

  stream.addEventListener('guard', (event) => {
    const data = parseJson(event.data)
    state.guardStatus = data
    renderGuardSummary()
    renderNodes()
    renderFleetSummary()
    renderNodeOverview()
    renderNodeMeta(getEffectiveSelectedStatus())
    renderIncidents()

    if (state.selectedNode) {
      const currentSummary = data?.nodes?.[state.selectedNode] || null
      state.selectedGuard = {
        ...(state.selectedGuard || {}),
        summary: currentSummary,
      }
      renderDoctorPanel()
    }
  })

  stream.addEventListener('activity', (event) => {
    const data = parseJson(event.data)
    appendActivity(data)
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
        renderAnalysisStats('gateway-normalized', state.events, aggregateHeatmapFallback(state.events))
        return
      }

      const analyzedEvents = Array.isArray(payload.events) ? payload.events : []
      renderAnalysisStats(payload.analyzer || 'javascript-fallback', analyzedEvents, payload.heatmap)
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
    renderNodeOverview()
    renderNodeMeta(getEffectiveSelectedStatus())
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

  const experimental = Boolean(state.capabilities.experimental_enabled)
  const wasmBuilt = Boolean(state.capabilities?.enhanced?.wasm_worker_built)
  const featureText = experimental
    ? wasmBuilt
      ? 'Experimental enabled · WASM ready'
      : 'Experimental enabled · JS analyzer active'
    : 'Experimental disabled'
  setFeatureBadge(featureText, !experimental)

  maybePromptToken(state.capabilities)
  renderFleetSummary()
  renderGuardSummary()
  renderDoctorPanel()
  renderActivityTimeline()
  updateActionButtons()

  if (!experimental) {
    showFleetError('WASM UI routes are disabled. Set WASM_UI_EXPERIMENTAL=1 and refresh.')
    setConnectionBadge('Stream disabled', true)
  }
}

async function boot() {
  bindInputs()
  initWorker()
  renderFleetSummary()
  renderGuardSummary()
  renderNodes()
  renderNodeOverview()
  renderNodeMeta(null)
  renderIncidents()
  renderDoctorPanel()
  renderActivityTimeline()
  updateAnalysisFromEvents([])
  updateActionButtons()

  try {
    await loadCapabilities()

    if (state.capabilities?.experimental_enabled) {
      await Promise.all([refreshGuardStatus(), refreshNodes()])
      connectStream()
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    showFleetError(message)
    setConnectionBadge('Unavailable', true)
    toast(`Failed to initialize UI: ${message}`, 'error')
  }
}

boot()
