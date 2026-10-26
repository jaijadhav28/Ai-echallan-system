import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, Cctv, Cpu, Gauge, MonitorPlay, RefreshCw, ShieldAlert } from 'lucide-react'
import api, { apiError } from '../lib/api'
import { useToast } from '../context/ToastContext'
import CameraTile from '../components/CameraTile'
import { Card, EmptyState, ErrorNote, Loader, PageHeader, Pill } from '../components/ui'
import { confidencePercent, formatDateTime, timeAgo } from '../lib/format'

const HEALTH_REFRESH_MS = 8000
const FEED_REFRESH_MS = 20000
const STREAM_FPS = 30

const LAYOUTS = [
  { value: 1, label: 'Single' },
  { value: 2, label: '2 per row' },
  { value: 3, label: '3 per row' },
  { value: 4, label: '4 per row' },
]

export default function LiveMonitoring() {
  const toast = useToast()
  const [cameras, setCameras] = useState([])
  const [health, setHealth] = useState({})
  const [pipeline, setPipeline] = useState(null)
  const [gpu, setGpu] = useState(null)
  const [recent, setRecent] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [columns, setColumns] = useState(2)
  const [detectingId, setDetectingId] = useState('')

  const loadCameras = useCallback(async () => {
    try {
      const { data } = await api.get('/api/cameras')
      setCameras(data.cameras)
      setError('')
    } catch (requestError) {
      setError(apiError(requestError))
    } finally {
      setLoading(false)
    }
  }, [])

  const loadHealth = useCallback(async () => {
    try {
      const { data } = await api.get('/api/cameras/health/all')
      setHealth(Object.fromEntries(data.cameras.map((item) => [item.camera_id, item])))
      setPipeline(data.pipeline)
      setGpu(data.gpu || null)
    } catch {
      /* transient */
    }
  }, [])

  const loadFeed = useCallback(async () => {
    try {
      const { data } = await api.get('/api/violations', { params: { limit: 6, page: 1 } })
      setRecent(data.violations)
    } catch {
      /* non critical */
    }
  }, [])

  useEffect(() => {
    loadCameras()
    loadHealth()
    loadFeed()
    const healthTimer = setInterval(loadHealth, HEALTH_REFRESH_MS)
    const feedTimer = setInterval(loadFeed, FEED_REFRESH_MS)
    const cameraTimer = setInterval(loadCameras, 60000)
    return () => {
      clearInterval(healthTimer)
      clearInterval(feedTimer)
      clearInterval(cameraTimer)
    }
  }, [loadCameras, loadHealth, loadFeed])

  const detectNow = async (camera) => {
    setDetectingId(camera.camera_id)
    try {
      const { data } = await api.post(`/api/cameras/${camera.camera_id}/detect-now`, null, {
        timeout: 20000,
      })
      if (data.violations_recorded > 0) {
        toast.success(`${camera.camera_id}: ${data.message}`)
      } else {
        toast.info(`${camera.camera_id}: ${data.message}`)
      }
      loadFeed()
      loadHealth()
    } catch (requestError) {
      toast.error(apiError(requestError))
    } finally {
      setDetectingId('')
    }
  }

  const enabled = useMemo(
    () => cameras.filter((camera) => camera.enabled !== false),
    [cameras],
  )

  useEffect(() => {
    if (!enabled.length) return
    const next = Math.min(4, Math.max(1, enabled.length))
    setColumns(next)
  }, [enabled.length])
  const onlineCount = enabled.filter(
    (camera) => (health[camera.camera_id]?.status || camera.health?.status) === 'ONLINE',
  ).length

  const gridClass =
    columns === 1
      ? 'grid-cols-1'
      : columns === 2
        ? 'grid-cols-1 xl:grid-cols-2'
        : columns === 3
          ? 'grid-cols-1 md:grid-cols-2 2xl:grid-cols-3'
          : 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4'

  if (loading) return <Loader label="Connecting to cameras..." />

  return (
    <>
      <PageHeader
        title="Live Monitoring"
        description="Enabled cameras stream in real time. Automatic AI violation detection runs every few seconds on online cameras."
        actions={
          <>
            <select
              className="input w-auto py-1.5 text-xs"
              value={columns}
              onChange={(event) => setColumns(Number(event.target.value))}
            >
              {LAYOUTS.map((layout) => (
                <option key={layout.value} value={layout.value}>
                  {layout.label}
                </option>
              ))}
            </select>
            <button type="button" className="btn-secondary btn-sm" onClick={loadCameras}>
              <RefreshCw size={14} /> Refresh
            </button>
          </>
        }
      />

      {error && <div className="mb-4"><ErrorNote message={error} /></div>}

      {enabled.length === 0 ? (
        <Card>
          <EmptyState
            icon={Cctv}
            title="No live cameras"
            description="Add a LIVE IP / RTSP camera and enable it to start real-time monitoring."
            action={
              <Link to="/cameras" className="btn-primary btn-sm">
                Go to Cameras
              </Link>
            }
          />
        </Card>
      ) : (
        <div className="space-y-5">
          <div className={`grid gap-5 ${gridClass}`}>
            {enabled.map((camera) => (
              <CameraTile
                key={camera.camera_id}
                camera={camera}
                health={health[camera.camera_id] || camera.health}
                fps={STREAM_FPS}
                onDetect={detectNow}
                detecting={detectingId === camera.camera_id}
                prominent={columns === 1}
              />
            ))}
          </div>

          <div className="card flex flex-col">
            <div className="border-b border-slate-200 px-3.5 py-2.5">
              <p className="text-sm font-semibold text-slate-900">System Status</p>
              <p className="text-xs text-slate-500">Capture and detection engine</p>
            </div>

            <div className="grid grid-cols-2 gap-3 p-4 lg:grid-cols-5">
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <MonitorPlay size={13} /> Cameras online
                </p>
                <p className="mt-1 text-2xl font-semibold text-slate-900">
                  {onlineCount}/{enabled.length}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <Gauge size={13} /> Detection cycles
                </p>
                <p className="mt-1 text-2xl font-semibold text-slate-900">
                  {pipeline?.cycles ?? 0}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <ShieldAlert size={13} /> Violations
                </p>
                <p className="mt-1 text-2xl font-semibold text-slate-900">
                  {pipeline?.violations_recorded ?? 0}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <Activity size={13} /> Pipeline
                </p>
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {pipeline?.running ? 'Running' : 'Stopped'}
                </p>
                <p className="text-xs text-slate-500">
                  Last cycle {timeAgo(pipeline?.last_detection_cycle)}
                </p>
              </div>
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  <Cpu size={13} /> Camera GPU
                </p>
                <p className="mt-1 text-sm font-semibold text-slate-900">
                  {gpu?.enabled ? (gpu.backend || 'GPU').toUpperCase() : 'CPU'}
                </p>
                <p className="truncate text-xs text-slate-500">
                  {gpu?.enabled
                    ? gpu.opencl_device || 'OpenCL acceleration active'
                    : 'GPU unavailable — CPU fallback'}
                </p>
              </div>
            </div>

            <div className="border-t border-slate-200 px-4 py-3">
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Latest detections
              </p>
              {recent.length === 0 ? (
                <p className="text-sm text-slate-500">Nothing detected yet.</p>
              ) : (
                <ul className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                  {recent.slice(0, 6).map((violation) => (
                    <li
                      key={violation.id}
                      className="flex items-center justify-between gap-2 rounded-lg bg-slate-50 px-3 py-2 text-xs"
                    >
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-slate-800">
                          {violation.violation_label}
                        </span>
                        <span className="block truncate text-slate-500">
                          {violation.camera_id} · {formatDateTime(violation.detected_at)}
                        </span>
                      </span>
                      <span className="shrink-0 font-mono text-slate-600">
                        {confidencePercent(violation.confidence)}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {pipeline?.last_error && (
              <p className="border-t border-amber-100 bg-amber-50 px-4 py-2 text-xs text-amber-800">
                Last pipeline error: {pipeline.last_error}
              </p>
            )}

            <div className="border-t border-slate-200 px-4 py-2.5">
              <Link to="/violations" className="btn-secondary btn-sm w-full sm:w-auto">
                Review all violations
              </Link>
            </div>
          </div>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-center gap-2 text-xs text-slate-500">
        {enabled.map((camera) => {
          const state = health[camera.camera_id] || camera.health || {}
          return (
            <span
              key={camera.camera_id}
              className="inline-flex items-center gap-2 rounded-full border border-slate-200 bg-white px-3 py-1"
            >
              <Pill status={state.status || 'CONNECTING'} />
              {camera.camera_id}
              <span className="text-slate-400">·</span>
              {(state.fps ?? 0).toFixed(1)} FPS
              <span className="text-slate-400">·</span>
              seen {timeAgo(state.last_seen)}
            </span>
          )
        })}
      </div>
    </>
  )
}
