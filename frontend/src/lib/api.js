import axios from 'axios'

const BASE_URL = import.meta.env.VITE_API_URL || ''
const TOKEN_KEY = 'rto.token'
const USER_KEY = 'rto.user'

export const tokenStore = {
  get: () => localStorage.getItem(TOKEN_KEY) || '',
  set: (token) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => {
    localStorage.removeItem(TOKEN_KEY)
    localStorage.removeItem(USER_KEY)
  },
  getUser: () => {
    try {
      return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
    } catch {
      return null
    }
  },
  setUser: (user) => localStorage.setItem(USER_KEY, JSON.stringify(user)),
}

const api = axios.create({ baseURL: BASE_URL, timeout: 20000 })

api.interceptors.request.use((config) => {
  const token = tokenStore.get()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const config = error.config
    const status = error.response?.status
    const dropped = !error.response && config && !config.__retried
    if (dropped && (error.code === 'ERR_NETWORK' || error.code === 'ECONNABORTED')) {
      config.__retried = true
      await new Promise((resolve) => setTimeout(resolve, 600))
      return api.request(config)
    }
    const isLoginCall = (config?.url || '').includes('/api/auth/')
    if (status === 401 && !isLoginCall) {
      tokenStore.clear()
      window.dispatchEvent(new CustomEvent('rto:session-expired'))
    }
    return Promise.reject(error)
  },
)

/** Turn any axios failure into a sentence a user can act on. */
export function apiError(error, fallback = 'Something went wrong. Please try again.') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((item) => `${(item.loc || []).slice(-1)[0] || 'field'}: ${item.msg}`)
      .join(', ')
  }
  if (error?.code === 'ECONNABORTED' || /timeout/i.test(error?.message || '')) {
    return 'Request took too long. Refresh the page - the backend may be busy.'
  }
  if (error?.code === 'ERR_NETWORK') {
    return 'The server did not respond. Check if the backend is running on port 8000.'
  }
  const status = error?.response?.status
  if (status === 500 || status === 502 || status === 503 || status === 504) {
    return 'Backend server is not running or unreachable on port 8000. Please start the backend using START.bat.'
  }
  return error?.message || fallback
}

/** Media URLs carry the token in the query string - <img> cannot set headers. */
export function cameraStreamUrl(cameraId, fps = 30) {
  return `${BASE_URL}/api/cameras/${encodeURIComponent(cameraId)}/stream?fps=${fps}&token=${tokenStore.get()}`
}

export function cameraSnapshotUrl(cameraId, cacheBuster = '') {
  return `${BASE_URL}/api/cameras/${encodeURIComponent(cameraId)}/snapshot?token=${tokenStore.get()}${
    cacheBuster ? `&t=${cacheBuster}` : ''
  }`
}

export function evidenceUrl(filename) {
  if (!filename) return ''
  return `${BASE_URL}/api/violations/evidence/${encodeURIComponent(filename)}?token=${tokenStore.get()}`
}

export function downloadUrl(path) {
  const separator = path.includes('?') ? '&' : '?'
  return `${BASE_URL}${path}${separator}token=${tokenStore.get()}`
}

export default api
