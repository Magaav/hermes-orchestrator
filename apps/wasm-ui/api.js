async function request(path, options = {}) {
  const headers = {
    ...(options.headers || {}),
  }

  const token = window.localStorage.getItem('wasm_ui_api_token') || ''
  if (token) {
    headers.Authorization = `Bearer ${token}`
  }

  const response = await fetch(path, {
    ...options,
    headers,
  })

  const payload = await response
    .json()
    .catch(() => ({ ok: false, error: `Non-JSON response (${response.status})` }))

  if (!response.ok || payload.ok === false) {
    throw new Error(payload.error || `Request failed: ${response.status}`)
  }

  return payload
}

export function getCapabilities() {
  return request('/api/fleet/capabilities')
}

export function listNodes() {
  return request('/api/fleet/nodes')
}

export function getNodeStatus(node) {
  return request(`/api/fleet/nodes/${encodeURIComponent(node)}/status`)
}

export function getNodeLogs(node, channel, tail) {
  const q = new URLSearchParams({
    channel,
    tail: String(tail),
  })
  return request(`/api/fleet/nodes/${encodeURIComponent(node)}/logs?${q.toString()}`)
}

export function runNodeAction(node, action) {
  return request(`/api/fleet/nodes/${encodeURIComponent(node)}/actions`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ action }),
  })
}
