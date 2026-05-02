import {
  getDashboardChannelDetail,
  getDashboardChannelSeries,
  getDashboardNodeChannels,
  getCapabilities,
  getGuardStatus,
  getNodeActivity,
  getNodeGuard,
  getNodeLogs,
  getNodeStatus,
  listDashboardNodes,
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
const DASHBOARD_REFRESH_SECONDS = 12
const HEADER_COPY = {
  ops: {
    title: 'Fleet Control Surface',
    subtitle: 'Freshness-first node operations, live diagnostics, and guided debugging layered over clone_manager.py.',
    note: 'Safe actions only. CLI remains canonical.',
  },
  dashboards: {
    title: 'Paracelsus Monitoring Surface',
    subtitle: 'One scientific dashboard: tokens in, papers in, and the evidence trail that explains how the registry is compounding.',
    note: 'Dashboard mode stays ACL-scoped and plugin-owned.',
  },
}

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
  view: 'dashboards',
  dashboardNodes: [],
  dashboardSelectedNode: null,
  dashboardSelectedChannel: '',
  dashboardNodeOverview: null,
  dashboardChannelDetail: null,
  dashboardSeries: {
    day: [],
    week: [],
    month: [],
  },
  dashboardRefreshRemaining: 12,
  dashboardLastRefreshAt: null,
  dashboardRefreshing: false,
}

let dashboardChart = null
let dashboardChartHost = null
let dashboardChartResizeObserver = null
let dashboardChartResizeTimer = 0
let dashboardWindowResizeBound = false

const elements = {
  featureBadge: document.getElementById('featureBadge'),
  connectionBadge: document.getElementById('connectionBadge'),
  headerTitle: document.getElementById('headerTitle'),
  headerSubtitle: document.getElementById('headerSubtitle'),
  headerNote: document.getElementById('headerNote'),
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
  opsModeBtn: document.getElementById('opsModeBtn'),
  dashboardsModeBtn: document.getElementById('dashboardsModeBtn'),
  opsWorkspace: document.getElementById('opsWorkspace'),
  dashboardWorkspace: document.getElementById('dashboardWorkspace'),
  refreshDashboardBtn: document.getElementById('refreshDashboardBtn'),
  dashboardRefreshBadge: document.getElementById('dashboardRefreshBadge'),
  dashboardRefreshStatus: document.getElementById('dashboardRefreshStatus'),
  dashboardLastEventValue: document.getElementById('dashboardLastEventValue'),
  dashboardLastPaperValue: document.getElementById('dashboardLastPaperValue'),
  dashboardNodesList: document.getElementById('dashboardNodesList'),
  dashboardNodeTitle: document.getElementById('dashboardNodeTitle'),
  dashboardNodeSummary: document.getElementById('dashboardNodeSummary'),
  dashboardNodeSignalStrip: document.getElementById('dashboardNodeSignalStrip'),
  dashboardSummaryGrid: document.getElementById('dashboardSummaryGrid'),
  dashboardChannelsList: document.getElementById('dashboardChannelsList'),
  dashboardSeriesStrip: document.getElementById('dashboardSeriesStrip'),
  dashboardCacheList: document.getElementById('dashboardCacheList'),
  dashboardSessionsList: document.getElementById('dashboardSessionsList'),
  dashboardProcessingList: document.getElementById('dashboardProcessingList'),
  dashboardLatestPapersList: document.getElementById('dashboardLatestPapersList'),
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

function formatNumber(value) {
  return Number(value || 0).toLocaleString()
}

function formatPercent(value, fractionDigits = 0) {
  const numeric = Number(value)
  if (!Number.isFinite(numeric)) return 'n/a'
  return `${numeric.toFixed(fractionDigits)}%`
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

function isDefaultDashboardChannelLabel(label) {
  return /^channel-\d{4,}$/.test(String(label || '').trim())
}

function dashboardChannelDisplayName(channel) {
  if (!channel) return 'No channel selected'

  const label = String(channel.label || '').trim()
  if (label && !isDefaultDashboardChannelLabel(label)) {
    return label
  }

  const commandLabel = asArray(channel.allowed_commands)[0] || asArray(channel.allowed_skills)[0] || ''
  if (commandLabel) {
    return startCase(String(commandLabel).replaceAll('-', ' '))
  }

  return label || String(channel.channel_id || 'Unknown Channel')
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

function formatRelativeTime(ts) {
  if (!ts) return 'waiting'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return String(ts)
  const diffMs = Date.now() - date.getTime()
  const diffSeconds = Math.max(0, Math.round(diffMs / 1000))
  if (diffSeconds < 60) return `${diffSeconds}s ago`
  const diffMinutes = Math.round(diffSeconds / 60)
  if (diffMinutes < 60) return `${diffMinutes}m ago`
  const diffHours = Math.round(diffMinutes / 60)
  if (diffHours < 48) return `${diffHours}h ago`
  const diffDays = Math.round(diffHours / 24)
  return `${diffDays}d ago`
}

function formatDashboardStamp(ts) {
  if (!ts) return 'Waiting'
  const date = new Date(ts)
  if (Number.isNaN(date.getTime())) return String(ts)
  return `${formatRelativeTime(ts)} · ${date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
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

function sumSeries(points, key) {
  return asArray(points).reduce((sum, point) => sum + Number(point?.[key] || 0), 0)
}

function peakSeriesPoint(points, key) {
  return asArray(points).reduce((best, point) => {
    const value = Number(point?.[key] || 0)
    if (!best || value > Number(best?.[key] || 0)) {
      return point
    }
    return best
  }, null)
}

function sparklineSvg(points, key, tone = 'watch') {
  const values = asArray(points).map((point) => Number(point?.[key] || 0))
  if (!values.length) {
    return '<div class="dashboard-sparkline is-empty">No curve yet</div>'
  }
  const width = 180
  const height = 56
  const padding = 6
  const min = Math.min(...values)
  const max = Math.max(...values)
  const span = Math.max(1, max - min)
  const path = values
    .map((value, index) => {
      const x = padding + ((width - padding * 2) * index) / Math.max(1, values.length - 1)
      const y = height - padding - ((value - min) / span) * (height - padding * 2)
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
  const area = `${path} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z`
  return `
    <div class="dashboard-sparkline tone-${tone}">
      <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" aria-hidden="true">
        <path class="dashboard-sparkline-area" d="${area}"></path>
        <path class="dashboard-sparkline-line" d="${path}"></path>
      </svg>
    </div>
  `
}

function dashboardCurveCardHtml(title, headline, tone, points, valueKey, rows) {
  const rowsHtml = rows
    .map((row) => `
      <div class="meta-row">
        <span>${escapeHtml(row.label)}</span>
        <strong>${escapeHtml(row.value)}</strong>
      </div>
    `)
    .join('')
  return `
    <article class="meta-card tone-${tone} dashboard-curve-card">
      <p class="meta-kicker">${escapeHtml(title)}</p>
      <h3>${escapeHtml(headline)}</h3>
      ${sparklineSvg(points, valueKey, tone)}
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
    cell.style.background = `rgba(248, 149, 33, ${alpha.toFixed(3)})`
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

function setView(view) {
  state.view = view === 'dashboards' ? 'dashboards' : 'ops'
  elements.opsWorkspace.classList.toggle('hidden', state.view !== 'ops')
  elements.dashboardWorkspace.classList.toggle('hidden', state.view !== 'dashboards')
  elements.opsModeBtn.classList.toggle('is-active', state.view === 'ops')
  elements.dashboardsModeBtn.classList.toggle('is-active', state.view === 'dashboards')
  document.body.classList.toggle('dashboard-mode', state.view === 'dashboards')
  renderModeHeader()
  renderDashboardRefreshState()
}

function renderModeHeader() {
  const copy = state.view === 'dashboards' ? HEADER_COPY.dashboards : HEADER_COPY.ops
  if (elements.headerTitle) {
    elements.headerTitle.textContent = copy.title
  }
  if (elements.headerSubtitle) {
    elements.headerSubtitle.textContent = copy.subtitle
  }
  if (elements.headerNote) {
    elements.headerNote.textContent = copy.note
  }
}

function dashboardNodeTone(node) {
  const totalPapers = Number(node?.extras?.cache?.total_papers || 0)
  const totalQueries = asArray(node?.extras?.cache?.event_series).reduce(
    (sum, point) => sum + Number(point?.query_count || 0),
    0,
  )
  const totalTokens = Number(node?.totals?.total_tokens || 0)
  const sessions = Number(node?.totals?.session_count || 0)
  if (totalPapers > 0 || totalQueries > 0) return 'good'
  if (totalTokens > 0 || sessions > 0) return 'good'
  return 'neutral'
}

function dashboardCache() {
  return state.dashboardChannelDetail?.extras?.cache || state.dashboardNodeOverview?.extras?.cache || null
}

function dashboardHitRate(cache) {
  const hits = Number(cache?.cache_hits || 0)
  const misses = Number(cache?.cache_misses || 0)
  const total = hits + misses
  return total > 0 ? (hits / total) * 100 : NaN
}

function dashboardCacheModeTone(mode) {
  const text = String(mode || '').toLowerCase()
  if (text === 'hit') return 'good'
  if (text === 'mixed') return 'watch'
  if (text === 'miss') return 'neutral'
  return 'neutral'
}

function dashboardQueryHtml(query) {
  const tone = dashboardCacheModeTone(query.cache_mode)
  return `
    <article class="dashboard-feed-card tone-${tone}">
      <div class="dashboard-feed-head">
        <strong>${escapeHtml(truncateText(query.query || 'Scientific cache event', 88))}</strong>
        <span>${escapeHtml(formatDashboardStamp(query.ts))}</span>
      </div>
      <p>${escapeHtml(`report ${query.report_id || 'pending'} · raw ${formatNumber(query.total_raw || 0)} · ranked ${formatNumber(query.total_deduplicated || query.papers_returned || 0)}`)}</p>
      <div class="timeline-meta-row">
        ${signalChipHtml(startCase(query.cache_mode || 'tracked'), tone)}
        ${signalChipHtml(`hit ${formatNumber(query.cache_hits || 0)}`, 'neutral')}
        ${signalChipHtml(`new ${formatNumber(query.asset_downloads || 0)} assets`, 'watch')}
      </div>
    </article>
  `
}

function dashboardSessionActivityTone(session) {
  const stamp = session?.ended_at || session?.started_at || ''
  if (!stamp) return 'neutral'
  const ageMs = Date.now() - new Date(stamp).getTime()
  if (!Number.isFinite(ageMs)) return 'neutral'
  if (ageMs <= 3 * 60 * 1000) return 'good'
  if (ageMs <= 20 * 60 * 1000) return 'watch'
  return 'neutral'
}

function dashboardProcessingHtml(session, peakTokens = 1) {
  const totalTokens = Number(session?.total_tokens || 0)
  const width = Math.max(8, Math.round((totalTokens / Math.max(1, peakTokens)) * 100))
  const tone = dashboardSessionActivityTone(session)
  const actor = String(session?.user_name || session?.display_name || 'session').trim()
  return `
    <article class="dashboard-processing-card tone-${tone}">
      <div class="dashboard-feed-head">
        <strong>${escapeHtml(truncateText(actor, 48))}</strong>
        <span>${escapeHtml(formatDashboardStamp(session?.ended_at || session?.started_at || ''))}</span>
      </div>
      <div class="dashboard-processing-bar">
        <span class="dashboard-processing-fill tone-${tone}" style="width:${width}%"></span>
      </div>
      <div class="timeline-meta-row">
        ${signalChipHtml(`${formatNumber(totalTokens)} tokens`, 'good')}
        ${signalChipHtml(`${formatNumber(session?.message_count || 0)} messages`, 'neutral')}
        ${signalChipHtml(`${formatNumber(session?.tool_call_count || 0)} tools`, 'watch')}
      </div>
    </article>
  `
}

function dashboardPaperHtml(paper) {
  const sources = asArray(paper.sources).filter(Boolean)
  const tone = sources.includes('pubmed') ? 'good' : 'watch'
  return `
    <article class="dashboard-paper-card tone-${tone}">
      <div class="dashboard-feed-head">
        <strong>${escapeHtml(truncateText(paper.title || 'Untitled paper', 96))}</strong>
        <span>${escapeHtml(formatDashboardStamp(paper.created_at))}</span>
      </div>
      <p>${escapeHtml(truncateText(paper.journal || 'Journal not tagged', 96))}</p>
      <div class="timeline-meta-row">
        ${paper.year ? signalChipHtml(String(paper.year), 'neutral') : ''}
        ${sources.slice(0, 2).map((source) => signalChipHtml(startCase(source), 'good')).join('')}
      </div>
      <div class="timeline-detail">${escapeHtml(paper.http_link || '')}</div>
    </article>
  `
}

function dashboardSessionHtml(session) {
  return `
    <article class="dashboard-feed-card tone-neutral">
      <div class="dashboard-feed-head">
        <strong>${escapeHtml(session.display_name || session.session_id || 'Session')}</strong>
        <span>${escapeHtml(formatDashboardStamp(session.started_at))}</span>
      </div>
      <p>${escapeHtml(`${formatNumber(session.message_count)} messages · ${formatNumber(session.tool_call_count)} tools · ${formatNumber(session.input_tokens)} in · ${formatNumber(session.output_tokens)} out`)}</p>
      <div class="timeline-meta-row">
        ${signalChipHtml(`${formatNumber(session.total_tokens || 0)} tokens`, 'neutral')}
        ${signalChipHtml(`${formatNumber(session.api_call_count || 0)} API`, 'watch')}
      </div>
    </article>
  `
}

function renderDashboardRefreshState() {
  if (!elements.dashboardRefreshBadge || !elements.dashboardRefreshStatus) {
    return
  }
  if (state.dashboardRefreshing) {
    elements.dashboardRefreshBadge.textContent = 'Refreshing live data...'
    elements.dashboardRefreshStatus.textContent = 'Refreshing'
    return
  }
  if (state.view !== 'dashboards') {
    elements.dashboardRefreshBadge.textContent = 'Dashboard paused'
    elements.dashboardRefreshStatus.textContent = 'Paused'
    return
  }
  const seconds = Math.max(0, Number(state.dashboardRefreshRemaining || 0))
  elements.dashboardRefreshBadge.textContent = state.dashboardLastRefreshAt
    ? `Refresh in ${seconds}s`
    : 'Initial refresh pending'
  elements.dashboardRefreshStatus.textContent = state.dashboardLastRefreshAt
    ? formatDashboardStamp(state.dashboardLastRefreshAt)
    : 'Waiting'
}

function startDashboardRefreshLoop() {
  window.setInterval(async () => {
    if (state.view !== 'dashboards' || state.dashboardRefreshing) {
      renderDashboardRefreshState()
      return
    }
    state.dashboardRefreshRemaining = Math.max(0, Number(state.dashboardRefreshRemaining || DASHBOARD_REFRESH_SECONDS) - 1)
    renderDashboardRefreshState()
    if (state.dashboardRefreshRemaining > 0) {
      return
    }
    state.dashboardRefreshRemaining = DASHBOARD_REFRESH_SECONDS
    await refreshDashboardNodes()
  }, 1000)
}

function renderDashboardNodes() {
  elements.dashboardNodesList.innerHTML = ''

  if (!state.dashboardNodes.length) {
    elements.dashboardNodesList.innerHTML = `
      <article class="empty-state">
        <strong>No dashboard nodes discovered.</strong>
        <p>Enable <code>PLUGIN_DASHBOARD=true</code> on a node and refresh this view.</p>
      </article>
    `
    return
  }

  for (const node of state.dashboardNodes) {
    const tone = dashboardNodeTone(node)
    const displayName = startCase(node.node || 'node')
    const cache = node?.extras?.cache || null
    const totalQueries = asArray(cache?.event_series).reduce(
      (sum, point) => sum + Number(point?.query_count || 0),
      0,
    )
    const monthlyTokens = asArray(node?.channels)
      .reduce((sum, channel) => sum + Number(channel?.total_tokens || 0), 0)
    const headline = cache
      ? `${formatNumber(cache.total_papers || 0)} papers`
      : `${formatNumber(monthlyTokens || node?.totals?.total_tokens || 0)} tokens`
    const card = document.createElement('button')
    card.type = 'button'
    card.className = `node-card tone-${tone}`
    if (node.node === state.dashboardSelectedNode) {
      card.classList.add('is-selected')
    }
    card.innerHTML = `
      <div class="node-card-top">
        <div>
          <div class="node-title-row">
            <span class="node-name">${escapeHtml(displayName)}</span>
            <span class="node-priority tone-${tone}">${escapeHtml(startCase(tone))}</span>
          </div>
          <p class="node-subline">
            ${cache
              ? `${formatNumber(totalQueries)} queries · ${formatNumber(monthlyTokens)} tokens tracked`
              : `${formatNumber(node?.totals?.channel_count || 0)} channels · ${formatNumber(monthlyTokens)} tokens`}
          </p>
        </div>
        <span class="node-status-pill tone-${tone}">
          ${escapeHtml(headline)}
        </span>
      </div>
      <div class="node-chip-row">
        ${cache
          ? signalChipHtml(`${formatNumber(cache.papers_today || 0)} today`, 'watch')
          : signalChipHtml(`${formatNumber(node?.totals?.input_tokens || 0)} in`, 'neutral')}
        ${cache
          ? signalChipHtml(`${formatNumber(cache.asset_downloads || 0)} new assets`, 'good')
          : signalChipHtml(`${formatNumber(node?.totals?.output_tokens || 0)} out`, 'neutral')}
        ${cache
          ? signalChipHtml(formatPercent(dashboardHitRate(cache)), 'neutral')
          : signalChipHtml(`${formatNumber(node?.totals?.message_count || 0)} msgs`, tone)}
      </div>
    `
    card.addEventListener('click', async () => {
      await loadDashboardNode(node.node, false)
    })
    elements.dashboardNodesList.appendChild(card)
  }
}

function disposeDashboardChart() {
  dashboardChart?.dispose?.()
  dashboardChart = null
  dashboardChartHost = null
  if (dashboardChartResizeObserver) {
    dashboardChartResizeObserver.disconnect()
    dashboardChartResizeObserver = null
  }
  if (dashboardChartResizeTimer) {
    window.clearTimeout(dashboardChartResizeTimer)
    dashboardChartResizeTimer = 0
  }
}

function scheduleDashboardChartResize() {
  if (!dashboardChart) return
  window.requestAnimationFrame(() => {
    dashboardChart?.resize?.()
  })
  if (dashboardChartResizeTimer) {
    window.clearTimeout(dashboardChartResizeTimer)
  }
  dashboardChartResizeTimer = window.setTimeout(() => {
    dashboardChart?.resize?.()
    dashboardChartResizeTimer = 0
  }, 150)
}

function buildDashboardSeriesPoints(paperSeries, eventSeries, tokenSeries) {
  const eventMap = new Map(eventSeries.map((point) => [String(point.bucket || ''), point]))
  const paperMap = new Map(paperSeries.map((point) => [String(point.bucket || ''), point]))
  const tokenMap = new Map(tokenSeries.map((point) => [String(point.bucket || ''), point]))
  const bucketOrder = [
    ...new Set([
      ...tokenSeries.map((point) => String(point.bucket || '')),
      ...paperSeries.map((point) => String(point.bucket || '')),
      ...eventSeries.map((point) => String(point.bucket || '')),
    ]),
  ]
  return bucketOrder.map((bucket) => ({
    bucket,
    totalTokens: Number(tokenMap.get(bucket)?.total_tokens || 0),
    papersAdded: Number(paperMap.get(bucket)?.papers_added || 0),
    cumulativePapers: Number(paperMap.get(bucket)?.cumulative_papers || 0),
    queryCount: Number(eventMap.get(bucket)?.query_count || 0),
  }))
}

function bindDashboardChartResize(host) {
  if (!host) return

  if (!dashboardWindowResizeBound) {
    window.addEventListener('resize', scheduleDashboardChartResize)
    dashboardWindowResizeBound = true
  }

  if (typeof window.ResizeObserver !== 'function') return

  if (!dashboardChartResizeObserver) {
    dashboardChartResizeObserver = new window.ResizeObserver(() => {
      scheduleDashboardChartResize()
    })
  } else {
    dashboardChartResizeObserver.disconnect()
  }

  const shell = host.closest('.dashboard-chart-shell')
  dashboardChartResizeObserver.observe(host)
  if (shell && shell !== host) {
    dashboardChartResizeObserver.observe(shell)
  }
  if (elements.dashboardSeriesStrip && elements.dashboardSeriesStrip !== shell) {
    dashboardChartResizeObserver.observe(elements.dashboardSeriesStrip)
  }
}

function ensureDashboardChartHost() {
  if (!elements.dashboardSeriesStrip.querySelector('#dashboardSeriesChart')) {
    elements.dashboardSeriesStrip.innerHTML = `
      <div class="dashboard-chart-shell">
        <div class="dashboard-chart-head">
          <strong>Token Demand And Memory Growth</strong>
          <span>Monthly token pressure, paper ingress, cumulative registry size, and query activity on one evidence surface</span>
        </div>
        <div id="dashboardSeriesChart" class="dashboard-chart"></div>
      </div>
    `
  }

  const nextHost = document.getElementById('dashboardSeriesChart')
  if (!nextHost) return null

  if (!dashboardChart || dashboardChartHost !== nextHost) {
    disposeDashboardChart()
    dashboardChart = window.echarts.init(nextHost)
    dashboardChartHost = nextHost
  }
  bindDashboardChartResize(nextHost)

  return dashboardChart
}

function dashboardChartOption(seriesPoints) {
  return {
    animationDuration: 180,
    animationDurationUpdate: 180,
    animationEasing: 'cubicOut',
    animationEasingUpdate: 'cubicOut',
    backgroundColor: 'transparent',
    color: ['#8e451f', '#f89521', '#f4c682', '#dec7b0'],
    grid: { left: 42, right: 24, top: 64, bottom: 34 },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(26, 18, 14, 0.96)',
      borderColor: 'rgba(248, 149, 33, 0.32)',
      textStyle: { color: '#f7f0e7' },
    },
    legend: {
      top: 6,
      textStyle: { color: '#ccb8a3', fontFamily: 'Space Grotesk' },
    },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: seriesPoints.map((point) => point.bucket),
      axisLabel: { color: '#ccb8a3', fontSize: 11 },
      axisLine: { lineStyle: { color: 'rgba(248, 149, 33, 0.25)' } },
    },
    yAxis: [
      {
        type: 'value',
        name: 'Tokens / queries',
        axisLabel: { color: '#ccb8a3', fontSize: 11 },
        splitLine: { lineStyle: { color: 'rgba(248, 149, 33, 0.12)' } },
      },
      {
        type: 'value',
        name: 'Papers',
        axisLabel: { color: '#ccb8a3', fontSize: 11 },
        splitLine: { show: false },
      },
    ],
    series: [
      {
        name: 'Tokens',
        type: 'line',
        smooth: true,
        showSymbol: false,
        data: seriesPoints.map((point) => point.totalTokens),
        lineStyle: { width: 3 },
        itemStyle: { color: '#8e451f' },
      },
      {
        name: 'New papers',
        type: 'bar',
        yAxisIndex: 1,
        data: seriesPoints.map((point) => point.papersAdded),
        barMaxWidth: 18,
        itemStyle: { borderRadius: [6, 6, 0, 0] },
      },
      {
        name: 'Registry size',
        type: 'line',
        smooth: true,
        showSymbol: false,
        yAxisIndex: 1,
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(244, 198, 130, 0.34)' },
              { offset: 1, color: 'rgba(244, 198, 130, 0.04)' },
            ],
          },
        },
        data: seriesPoints.map((point) => point.cumulativePapers),
      },
      {
        name: 'Queries',
        type: 'line',
        smooth: true,
        showSymbol: false,
        lineStyle: { type: 'dashed' },
        data: seriesPoints.map((point) => point.queryCount),
      },
    ],
  }
}

function renderDashboardSeries() {
  const cache = dashboardCache()
  const paperSeries = asArray(cache?.paper_series)
  const eventSeries = asArray(cache?.event_series)
  const tokenSeries = asArray(state.dashboardSeries.month)
  if (!paperSeries.length && !eventSeries.length && !tokenSeries.length) {
    disposeDashboardChart()
    elements.dashboardSeriesStrip.innerHTML = `
      <article class="empty-state">
        <strong>No growth curve yet.</strong>
        <p>The chart will wake up as soon as Paracelsus logs token traffic or persists new papers.</p>
      </article>
    `
    return
  }

  if (window.echarts && (paperSeries.length || tokenSeries.length)) {
    const seriesPoints = buildDashboardSeriesPoints(paperSeries, eventSeries, tokenSeries)
    const chart = ensureDashboardChartHost()
    if (chart) {
      chart.setOption(dashboardChartOption(seriesPoints), {
        notMerge: false,
        lazyUpdate: true,
        replaceMerge: ['xAxis', 'yAxis', 'series'],
      })
      scheduleDashboardChartResize()
    }
    return
  }

  const ceiling = Math.max(1, ...paperSeries.map((point) => Number(point.cumulative_papers || 0)))
  elements.dashboardSeriesStrip.innerHTML = `
    <div class="dashboard-bars">
      ${paperSeries
        .map((point) => {
          const totalPapers = Number(point.cumulative_papers || 0)
          const height = Math.max(10, Math.round((totalPapers / ceiling) * 100))
          return `
            <article class="dashboard-bar-card">
              <div class="dashboard-bar-head">
                <strong>${escapeHtml(point.bucket || '--')}</strong>
                <span>${escapeHtml(formatNumber(totalPapers))} papers</span>
              </div>
              <div class="dashboard-bar-track">
                <span class="dashboard-bar-fill" style="height:${height}%"></span>
              </div>
              <div class="dashboard-bar-meta">
                <span>${escapeHtml(formatNumber(point.papers_added || 0))} new</span>
                <span>${escapeHtml(formatNumber(eventSeries.find((item) => item.bucket === point.bucket)?.query_count || 0))} queries</span>
              </div>
            </article>
          `
        })
        .join('')}
    </div>
  `
}

function renderDashboardExtras() {
  const extras = state.dashboardChannelDetail?.extras || state.dashboardNodeOverview?.extras || {}
  const cards = []

  if (extras.cache) {
    const cache = extras.cache
    const hitRate = dashboardHitRate(cache)
    cards.push(
      metricCardHtml('Registry', `${formatNumber(cache.total_papers)} papers`, 'watch', [
        { label: 'Today', value: formatNumber(cache.papers_today || 0) },
        { label: 'Links', value: formatNumber(cache.unique_links || 0) },
        { label: 'Latest', value: formatRelativeTime(cache.latest_paper_ts) },
      ]),
    )
    cards.push(
      metricCardHtml('Lookup Flow', `${formatPercent(hitRate)} hit rate`, 'good', [
        { label: 'Hits', value: formatNumber(cache.cache_hits || 0) },
        { label: 'Misses', value: formatNumber(cache.cache_misses || 0) },
        { label: 'Queries', value: formatNumber(asArray(cache.recent_queries).length) },
      ]),
    )
    cards.push(
      metricCardHtml('Storage', shortenPath(cache.db_path, 3), 'neutral', [
        { label: 'Files', value: shortenPath(cache.files_root, 3), title: cache.files_root || '' },
        { label: 'Events', value: shortenPath(cache.log_path, 3), title: cache.log_path || '' },
        { label: 'Assets', value: formatNumber(cache.asset_directories || 0) },
      ]),
    )
    if (asArray(cache.source_mix).length) {
      cards.push(
        metricCardHtml(
          'Source Mix',
          startCase(cache.source_mix[0]?.source || 'n/a'),
          'good',
          asArray(cache.source_mix)
            .slice(0, 3)
            .map((item) => ({
              label: startCase(item.source || 'source'),
              value: formatNumber(item.count || 0),
            })),
        ),
      )
    }
    if (asArray(cache.top_journals).length) {
      cards.push(
        metricCardHtml(
          'Top Journals',
          cache.top_journals[0]?.journal || 'n/a',
          'watch',
          asArray(cache.top_journals)
            .slice(0, 3)
            .map((item) => ({
              label: truncateText(item.journal || 'journal', 18),
              value: formatNumber(item.count || 0),
              title: item.journal || '',
            })),
        ),
      )
    }
  }

  if (extras.operations) {
    const operations = extras.operations
    cards.push(
      metricCardHtml('Colmeio Ops', `${formatNumber(operations.total_operations || 0)} records`, 'good', [
        { label: 'Top trigger', value: operations.triggers?.[0]?.trigger_name || 'n/a' },
        { label: 'Top skill', value: operations.skills?.[0]?.skill_name || 'n/a' },
        { label: 'Top action', value: operations.skills?.[0]?.skill_action || 'n/a' },
      ]),
    )
  }

  elements.dashboardCacheList.innerHTML =
    cards.length
      ? `
          <div class="dashboard-extras-stack">
            <div class="dashboard-extras-grid">${cards.join('')}</div>
          </div>
        `
      : `
          <article class="empty-state">
            <strong>No node-specific extras yet.</strong>
            <p>Scientific cache telemetry and Colmeio ops metrics will appear here when available.</p>
          </article>
        `
}

function renderDashboardWorkspace() {
  const overview = state.dashboardNodeOverview
  if (!overview) {
    elements.dashboardNodeTitle.textContent = 'Paracelsus Analytics'
    elements.dashboardNodeSummary.textContent = 'Select a dashboard-enabled node to inspect channel metrics.'
    elements.dashboardNodeSignalStrip.innerHTML = signalChipHtml('Awaiting dashboard data', 'neutral')
    elements.dashboardSummaryGrid.innerHTML = `
      <article class="empty-state">
        <strong>No dashboard node selected.</strong>
        <p>Choose a node from the left rail to load its dashboard channels.</p>
      </article>
    `
    elements.dashboardChannelsList.innerHTML = ''
    elements.dashboardLastEventValue.textContent = 'Waiting'
    elements.dashboardLastPaperValue.textContent = 'Waiting'
    elements.dashboardSessionsList.innerHTML = `
      <article class="empty-state">
        <strong>No crawl feed yet.</strong>
        <p>Recent Paracelsus queries will appear here once the registry lane is active.</p>
      </article>
    `
    elements.dashboardProcessingList.innerHTML = `
      <article class="empty-state">
        <strong>No processing lane yet.</strong>
        <p>Recent session load will appear here once the selected channel receives traffic.</p>
      </article>
    `
    elements.dashboardLatestPapersList.innerHTML = `
      <article class="empty-state">
        <strong>No papers persisted yet.</strong>
        <p>The latest registry entries will appear here as soon as the cache starts growing.</p>
      </article>
    `
    renderDashboardSeries()
    renderDashboardExtras()
    renderDashboardRefreshState()
    return
  }

  const detail = state.dashboardChannelDetail
  const totals = overview.totals || {}
  const selectedChannelLabel = detail ? dashboardChannelDisplayName(detail) : 'No channel selected'
  const cache = dashboardCache()
  const hitRate = dashboardHitRate(cache)
  const recentQueries = asArray(cache?.recent_queries)
  const latestPapers = asArray(cache?.latest_papers)
  const recentSessions = asArray(detail?.recent_sessions)
  const daySeries = asArray(state.dashboardSeries.day)
  const weekSeries = asArray(state.dashboardSeries.week)
  const monthSeries = asArray(state.dashboardSeries.month)
  const totalQueries = asArray(cache?.event_series).reduce(
    (sum, point) => sum + Number(point?.query_count || 0),
    0,
  )
  const todayTokens = sumSeries(daySeries, 'total_tokens')
  const weekTokens = sumSeries(weekSeries, 'total_tokens')
  const monthTokens = sumSeries(monthSeries, 'total_tokens')
  const todayPeak = peakSeriesPoint(daySeries, 'total_tokens')
  const weekPeak = peakSeriesPoint(weekSeries, 'total_tokens')
  const monthPeak = peakSeriesPoint(monthSeries, 'total_tokens')

  elements.dashboardNodeTitle.textContent = `${startCase(overview.node || 'node')} Analytics`
  elements.dashboardNodeSummary.textContent =
    `${selectedChannelLabel} · ${formatNumber(cache?.total_papers || 0)} registry papers · ${formatNumber(monthTokens)} tokens tracked this month`
  elements.dashboardNodeSignalStrip.innerHTML = [
    signalChipHtml(`${formatNumber(cache?.papers_today || 0)} papers today`, 'watch'),
    signalChipHtml(`${formatNumber(weekTokens)} tokens this week`, 'good'),
    signalChipHtml(`${formatNumber(monthTokens)} tokens this month`, 'neutral'),
    signalChipHtml(selectedChannelLabel, detail ? 'watch' : 'neutral'),
  ].join('')
  elements.dashboardLastEventValue.textContent = formatDashboardStamp(cache?.latest_event_ts)
  elements.dashboardLastPaperValue.textContent = formatDashboardStamp(cache?.latest_paper_ts)

  const summaryCards = [
    dashboardCurveCardHtml('Today Tokens', `${formatNumber(todayTokens)} tokens`, 'watch', daySeries, 'total_tokens', [
      { label: '24h sessions', value: formatNumber(sumSeries(daySeries, 'session_count')) },
      { label: 'Peak hour', value: todayPeak ? `${formatDashboardStamp(todayPeak.bucket)} · ${formatNumber(todayPeak.total_tokens)} tokens` : 'Waiting' },
      { label: 'Output', value: formatNumber(sumSeries(daySeries, 'output_tokens')) },
    ]),
    dashboardCurveCardHtml('This Week', `${formatNumber(weekTokens)} tokens`, 'good', weekSeries, 'total_tokens', [
      { label: '7d sessions', value: formatNumber(sumSeries(weekSeries, 'session_count')) },
      { label: 'Peak day', value: weekPeak ? `${weekPeak.bucket} · ${formatNumber(weekPeak.total_tokens)} tokens` : 'Waiting' },
      { label: 'Messages', value: formatNumber(sumSeries(weekSeries, 'message_count')) },
    ]),
    dashboardCurveCardHtml('This Month', `${formatNumber(monthTokens)} tokens`, 'neutral', monthSeries, 'total_tokens', [
      { label: '30d sessions', value: formatNumber(sumSeries(monthSeries, 'session_count')) },
      { label: 'Peak day', value: monthPeak ? `${monthPeak.bucket} · ${formatNumber(monthPeak.total_tokens)} tokens` : 'Waiting' },
      { label: 'Input', value: formatNumber(sumSeries(monthSeries, 'input_tokens')) },
    ]),
    dashboardCurveCardHtml('Memory Growth', `${formatNumber(cache?.total_papers || 0)} papers`, 'watch', asArray(cache?.paper_series), 'cumulative_papers', [
      { label: 'New today', value: formatNumber(cache?.papers_today || 0) },
      { label: '30d queries', value: formatNumber(totalQueries) },
      { label: 'Cache hit rate', value: formatPercent(hitRate) },
    ]),
  ]

  elements.dashboardSummaryGrid.innerHTML = summaryCards.join('')

  const channels = asArray(overview.channels)
  if (!channels.length) {
    elements.dashboardChannelsList.innerHTML = `
      <article class="empty-state">
        <strong>No ACL-scoped channels found.</strong>
        <p>Only conditioned channels are rendered in dashboard mode.</p>
      </article>
    `
  } else {
    elements.dashboardChannelsList.innerHTML = channels
      .map((channel) => {
        const isActive = String(channel.channel_id) === String(state.dashboardSelectedChannel)
        const displayName = dashboardChannelDisplayName(channel)
        const descriptor =
          asArray(channel.allowed_commands)[0] ||
          asArray(channel.allowed_skills)[0] ||
          channel.channel_id
        return `
          <button type="button" class="dashboard-channel-card${isActive ? ' is-active' : ''}" data-dashboard-channel="${escapeHtml(channel.channel_id)}">
            <strong>${escapeHtml(displayName)}</strong>
            <span>${escapeHtml(startCase(String(descriptor).replaceAll('-', ' ')))}</span>
            <div class="timeline-meta-row">
              ${signalChipHtml(`${formatNumber(channel.total_tokens || 0)} tokens`, 'good')}
              ${signalChipHtml(`${formatNumber(channel.message_count || 0)} messages`, 'neutral')}
              ${signalChipHtml(`${formatDashboardStamp(channel.last_activity || '')}`, 'watch')}
            </div>
            <p class="dashboard-channel-footnote">${escapeHtml(channel.channel_id)}</p>
          </button>
        `
      })
      .join('')

    for (const button of elements.dashboardChannelsList.querySelectorAll('[data-dashboard-channel]')) {
      button.addEventListener('click', async () => {
        const channelId = button.getAttribute('data-dashboard-channel') || ''
        await loadDashboardChannel(state.dashboardSelectedNode, channelId)
      })
    }
  }

  elements.dashboardSessionsList.innerHTML =
    recentQueries.length
      ? recentQueries.map((query) => dashboardQueryHtml(query)).join('')
      : `
          <article class="empty-state">
            <strong>No query feed yet.</strong>
            <p>Once Paracelsus records a run summary, this feed will reflect the crawl in real time.</p>
          </article>
        `
  const peakSessionTokens = recentSessions.reduce(
    (best, session) => Math.max(best, Number(session?.total_tokens || 0)),
    1,
  )
  elements.dashboardProcessingList.innerHTML =
    recentSessions.length
      ? recentSessions.map((session) => dashboardProcessingHtml(session, peakSessionTokens)).join('')
      : `
          <article class="empty-state">
            <strong>No recent sessions in this lane.</strong>
            <p>The processing graph fills as soon as the selected channel records tracked sessions.</p>
          </article>
        `
  elements.dashboardLatestPapersList.innerHTML =
    latestPapers.length
      ? latestPapers.map((paper) => dashboardPaperHtml(paper)).join('')
      : Number(cache?.total_papers || 0) > 0
        ? `
            <article class="empty-state">
              <strong>${formatNumber(cache.total_papers || 0)} papers are already in the registry.</strong>
              <p>The dashboard could not build the latest-paper preview, but the database is growing and the chart above reflects it.</p>
            </article>
          `
      : `
          <article class="empty-state">
            <strong>No papers persisted yet.</strong>
            <p>Registry entries will appear here as soon as the scientific pipeline writes them.</p>
          </article>
        `

  renderDashboardSeries()
  renderDashboardExtras()
  renderDashboardRefreshState()
}

async function loadDashboardChannel(node, channelId) {
  if (!node || !channelId) {
    state.dashboardChannelDetail = null
    state.dashboardSeries = { day: [], week: [], month: [] }
    renderDashboardWorkspace()
    return
  }

  try {
    const [detailPayload, dayPayload, weekPayload, monthPayload] = await Promise.all([
      getDashboardChannelDetail(node, channelId),
      getDashboardChannelSeries(node, channelId, '24h'),
      getDashboardChannelSeries(node, channelId, '7d'),
      getDashboardChannelSeries(node, channelId, '30d'),
    ])
    state.dashboardSelectedChannel = channelId
    state.dashboardChannelDetail = detailPayload.channel || null
    state.dashboardSeries = {
      day: asArray(dayPayload.series?.points),
      week: asArray(weekPayload.series?.points),
      month: asArray(monthPayload.series?.points),
    }
    renderDashboardWorkspace()
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed to load dashboard channel: ${message}`, 'error')
  }
}

async function loadDashboardNode(node, preserveChannel = true) {
  if (!node) return
  try {
    const payload = await getDashboardNodeChannels(node)
    state.dashboardSelectedNode = node
    state.dashboardNodeOverview = payload.overview || null
    renderDashboardNodes()

    const channels = asArray(payload.channels)
    const currentChannelStillValid = channels.some(
      (channel) => String(channel.channel_id) === String(state.dashboardSelectedChannel),
    )
    if (!preserveChannel || !currentChannelStillValid) {
      state.dashboardSelectedChannel = channels[0]?.channel_id || ''
    }
    state.dashboardChannelDetail = null
    state.dashboardSeries = { day: [], week: [], month: [] }
    renderDashboardWorkspace()
    await loadDashboardChannel(node, state.dashboardSelectedChannel)
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed to load dashboard node: ${message}`, 'error')
  }
}

async function refreshDashboardNodes() {
  state.dashboardRefreshing = true
  renderDashboardRefreshState()
  try {
    const payload = await listDashboardNodes()
    state.dashboardNodes = asArray(payload.nodes)
    renderDashboardNodes()

    if (!state.dashboardSelectedNode && state.dashboardNodes[0]) {
      state.dashboardSelectedNode = state.dashboardNodes[0].node
    }

    if (state.dashboardSelectedNode) {
      await loadDashboardNode(state.dashboardSelectedNode)
    } else {
      state.dashboardNodeOverview = null
      state.dashboardChannelDetail = null
      state.dashboardSeries = { day: [], week: [], month: [] }
      renderDashboardWorkspace()
    }
    state.dashboardLastRefreshAt = new Date().toISOString()
    state.dashboardRefreshRemaining = DASHBOARD_REFRESH_SECONDS
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error)
    toast(`Failed to refresh dashboards: ${message}`, 'error')
  } finally {
    state.dashboardRefreshing = false
    renderDashboardRefreshState()
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

  elements.refreshDashboardBtn.addEventListener('click', async () => {
    await refreshDashboardNodes()
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

  elements.opsModeBtn.addEventListener('click', () => {
    setView('ops')
  })

  elements.dashboardsModeBtn.addEventListener('click', async () => {
    setView('dashboards')
    if (!state.dashboardNodes.length) {
      await refreshDashboardNodes()
    }
  })

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
  renderDashboardNodes()
  renderDashboardWorkspace()
  updateActionButtons()

  if (!experimental) {
    showFleetError('WASM UI routes are disabled. Set WASM_UI_EXPERIMENTAL=1 and refresh.')
    setConnectionBadge('Stream disabled', true)
  }
}

async function boot() {
  bindInputs()
  startDashboardRefreshLoop()
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
  renderDashboardNodes()
  renderDashboardWorkspace()
  setView('dashboards')

  try {
    await loadCapabilities()

    if (state.capabilities?.experimental_enabled) {
      await Promise.all([refreshGuardStatus(), refreshNodes(), refreshDashboardNodes()])
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
