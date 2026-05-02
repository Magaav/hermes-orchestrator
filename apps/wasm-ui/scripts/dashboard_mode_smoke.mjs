import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)
const appRoot = path.resolve(__dirname, '..')

const storage = new Map()
globalThis.window = {
  localStorage: {
    getItem(key) {
      return storage.get(key) || ''
    },
    setItem(key, value) {
      storage.set(key, value)
    },
  },
}

globalThis.fetch = async (url, options = {}) => ({
  ok: true,
  status: 200,
  async json() {
    return { ok: true, url, options }
  },
})

const api = await import(pathToFileURL(path.join(appRoot, 'api.js')).href)

const detail = await api.getDashboardChannelDetail('paracelsus', '1497340589191204898')
const series = await api.getDashboardChannelSeries('paracelsus', '1497340589191204898', '30d')
assert.equal(detail.url, '/api/fleet/dashboard/nodes/paracelsus/channels/1497340589191204898')
assert.equal(series.url, '/api/fleet/dashboard/nodes/paracelsus/channels/1497340589191204898/series?window=30d')

const html = await fs.readFile(path.join(appRoot, 'index.html'), 'utf8')
assert.match(html, /id="dashboardWorkspace"/)
assert.match(html, /id="dashboardNodesList"/)
assert.match(html, /id="dashboardsModeBtn"/)

console.log('dashboard mode smoke passed')
