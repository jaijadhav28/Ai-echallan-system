import { useEffect, useRef, useState } from 'react'
import {
  AlertTriangle,
  Camera,
  Pause,
  Play,
  PowerOff,
  RefreshCw,
  ScanSearch,
  ShieldAlert,
  WifiOff,
} from 'lucide-react'
import { cameraStreamUrl } from '../lib/api'
import { LiveDot, Pill } from './ui'
import { timeAgo } from '../lib/format'

/**
 * One independent camera feed. The MJPEG <img> reconnects on its own, so a
 * camera going offline never affects the other tiles on the page.
 */
export default function CameraTile({
  camera,
  health,
  fps = 30,
  onDetect,
  onToggle,
  onToggleDetection,
  detecting,
  prominent = false,
}) {
  const [streamKey, setStreamKey] = useState(() => Date.now())
  const [imageFailed, setImageFailed] = useState(false)
  const retryTimer = useRef(null)

  const status = health?.status || camera.status || 'CONNECTING'
  const online = status === 'ONLINE'
  const mode = (camera.mode || 'LIVE').toUpperCase()
  const isLive = mode === 'LIVE'
  const isDemo = mode === 'DEMO'

  useEffect(() => {
    if (!imageFailed) return undefined
    retryTimer.current = setTimeout(() => {
      setImageFailed(false)
      setStreamKey(Date.now())
    }, 3000)
    return () => clearTimeout(retryTimer.current)
  }, [imageFailed])

  const reconnect = () => {
    setImageFailed(false)
    setStreamKey(Date.now())
  }

  const frameClass = prominent
    ? 'relative w-full aspect-video max-h-[calc(100dvh-9rem)] bg-black overflow-hidden'
    : 'relative w-full aspect-video bg-black overflow-hidden'

  return (
    <div className={`card overflow-hidden ${prominent ? 'shadow-lg ring-1 ring-slate-200' : ''}`}>
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-3.5 py-2.5">
        <div className="flex min-w-0 items-center gap-2">
          <LiveDot online={online} />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-slate-900 sm:text-base">
              {camera.camera_id} · {camera.name}
            </p>
            <p className="truncate text-xs text-slate-500">
              {camera.location || 'Location not set'}
              {health?.resolution ? ` · ${health.resolution}` : ''}
              {String(health?.resolution || '').startsWith('3840') ? ' · 4K' : ''}
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5">
          {isDemo && <Pill status="DEMO" label="DEMO" />}
          {isLive && <Pill status="LIVE" label="LIVE" />}
          <Pill status={status} />
        </div>
      </div>

      <div className={frameClass}>
        {camera.enabled === false ? (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-3 p-6 text-center text-slate-300">
            <div className="rounded-full bg-slate-800/80 p-3 text-amber-400 ring-1 ring-amber-400/30">
              <PowerOff size={28} />
            </div>
            <div>
              <p className="text-sm font-semibold text-white">
                {isDemo ? 'Demo Traffic Simulation Paused' : 'Camera Disabled'}
              </p>
              <p className="mt-0.5 max-w-xs text-xs text-slate-400">
                {isDemo
                  ? 'Synthetic vehicles and automatic demo violation entries are stopped.'
                  : 'Capture thread and detection pipeline are stopped.'}
              </p>
            </div>
            {onToggle && (
              <button
                type="button"
                className="btn-primary btn-sm mt-1 flex items-center gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white shadow"
                onClick={() => onToggle(camera)}
              >
                <Play size={13} /> {isDemo ? 'Start Demo Violations' : 'Enable Camera'}
              </button>
            )}
          </div>
        ) : imageFailed ? (
          <div className="flex h-full min-h-[240px] flex-col items-center justify-center gap-2 px-4 text-center text-slate-300">
            <WifiOff size={26} className="text-rose-400" />
            <p className="text-sm font-medium">Stream unavailable</p>
            <p className="max-w-xs text-xs text-slate-400">
              {health?.connection_error || 'Reconnecting automatically...'}
            </p>
            <button type="button" className="btn-secondary btn-sm mt-1" onClick={reconnect}>
              <RefreshCw size={13} /> Retry now
            </button>
          </div>
        ) : (
          <img
            key={streamKey}
            src={cameraStreamUrl(camera.camera_id, fps)}
            alt={`${camera.camera_id} live stream`}
            className="absolute inset-0 h-full w-full object-contain object-center"
            style={{ imageRendering: 'auto' }}
            decoding="sync"
            fetchPriority="high"
            onError={() => setImageFailed(true)}
          />
        )}

        {!online && !imageFailed && camera.enabled !== false && (
          <span className="absolute left-2 top-12 z-20 flex items-center gap-1 rounded bg-rose-600/90 px-2 py-0.5 text-[11px] font-semibold text-white">
            <AlertTriangle size={12} /> {status}
          </span>
        )}

        <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-between gap-3 bg-[#16181d] px-3 py-2">
          <p className="min-w-0 truncate text-sm font-medium tracking-wide text-white">
            {camera.camera_id} | {camera.name}
          </p>
          <span
            className={`shrink-0 rounded-sm px-2 py-0.5 text-[11px] font-extrabold uppercase tracking-wide ${
              isDemo ? 'bg-amber-400 text-black' : 'bg-emerald-400 text-black'
            }`}
          >
            {isDemo ? 'DEMO MODE' : 'LIVE'}
          </span>
        </div>
      </div>

      <dl
        className={`grid gap-x-3 gap-y-1.5 px-3.5 py-3 text-xs ${
          prominent ? 'grid-cols-2 sm:grid-cols-5' : 'grid-cols-2 sm:grid-cols-4'
        }`}
      >
        <div>
          <dt className="text-slate-500">IP address</dt>
          <dd className="truncate font-mono text-slate-800">{camera.ip_address || '-'}</dd>
        </div>
        <div>
          <dt className="text-slate-500">FPS</dt>
          <dd className="font-medium text-slate-800">{(health?.fps ?? 0).toFixed(1)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Resolution</dt>
          <dd className="font-medium text-slate-800">
            {health?.resolution || '—'}
            {String(health?.resolution || '').startsWith('3840') ? ' · 4K' : ''}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Last frame</dt>
          <dd className="text-slate-800">{timeAgo(health?.last_frame_at)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Violations</dt>
          <dd className="font-medium text-slate-800">{health?.violation_count ?? 0}</dd>
        </div>
      </dl>

      {health?.connection_error && (
        <p className="border-t border-rose-100 bg-rose-50 px-3.5 py-2 text-xs text-rose-700">
          {health.connection_error}
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-200 px-3.5 py-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {onToggle && isDemo && (
            <button
              type="button"
              className={`btn-sm flex items-center gap-1 rounded px-2.5 py-1 text-xs font-semibold transition ${
                camera.enabled !== false
                  ? 'border border-rose-200 bg-rose-50 text-rose-700 hover:bg-rose-100'
                  : 'border border-emerald-300 bg-emerald-50 text-emerald-700 hover:bg-emerald-100'
              }`}
              onClick={() => onToggle(camera)}
              title={camera.enabled !== false ? 'Stop demo violations' : 'Start demo violations'}
            >
              {camera.enabled !== false ? <Pause size={12} /> : <Play size={12} />}
              {camera.enabled !== false ? 'Stop Demo' : 'Start Demo'}
            </button>
          )}

          {onToggleDetection && camera.enabled !== false && (
            <button
              type="button"
              className={`btn-sm flex items-center gap-1 rounded border px-2 py-1 text-xs transition ${
                health?.detection_enabled !== false && camera.detection_enabled !== false
                  ? 'border-indigo-200 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
                  : 'border-slate-300 bg-slate-100 text-slate-600 hover:bg-slate-200'
              }`}
              onClick={() => onToggleDetection(camera)}
              title="Toggle AI detector for this camera"
            >
              <ShieldAlert size={12} />
              {health?.detection_enabled !== false && camera.detection_enabled !== false
                ? 'AI Active'
                : 'AI Paused'}
            </button>
          )}

          {!isDemo && (
            <span className="text-xs text-slate-500">
              {health?.detection_enabled === false
                ? 'Detection disabled'
                : 'Detector ready'}
            </span>
          )}
        </div>

        {onDetect && (
          <button
            type="button"
            className="btn-secondary btn-sm"
            onClick={() => onDetect(camera)}
            disabled={detecting || !online || camera.enabled === false}
          >
            <ScanSearch size={13} className={detecting ? 'animate-pulse' : ''} /> Detect now
          </button>
        )}
      </div>
    </div>
  )
}
