import { useCallback, useEffect, useState } from 'react'
import {
  Cctv,
  Pencil,
  Plug,
  Plus,
  Power,
  RefreshCw,
  RotateCw,
  Trash2,
} from 'lucide-react'
import api, { apiError } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import {
  Card,
  EmptyState,
  ErrorNote,
  Field,
  InfoNote,
  Loader,
  Modal,
  PageHeader,
  Pill,
  StatCard,
} from '../components/ui'
import { timeAgo } from '../lib/format'

const EMPTY_FORM = {
  name: '',
  camera_id: '',
  ip_address: '',
  rtsp_url: '',
  username: '',
  password: '',
  location: '',
  description: '',
  mode: 'LIVE',
  demo_source_type: '',
  demo_source_path: '',
  enabled: true,
  detection_enabled: true,
  allowed_direction: 'ANY',
}

const DIRECTIONS = [
  { value: 'ANY', label: 'Any direction (no wrong-side check)' },
  { value: 'LEFT_TO_RIGHT', label: 'Left to right' },
  { value: 'RIGHT_TO_LEFT', label: 'Right to left' },
  { value: 'TOP_TO_BOTTOM', label: 'Top to bottom' },
  { value: 'BOTTOM_TO_TOP', label: 'Bottom to top' },
]

export default function Cameras() {
  const { isAdmin } = useAuth()
  const toast = useToast()

  const [cameras, setCameras] = useState([])
  const [summary, setSummary] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [modalOpen, setModalOpen] = useState(false)
  const [editing, setEditing] = useState(null)
  const [form, setForm] = useState(EMPTY_FORM)
  const [saving, setSaving] = useState(false)
  const [formError, setFormError] = useState('')
  const [testResult, setTestResult] = useState(null)
  const [testing, setTesting] = useState('')
  const [confirmDelete, setConfirmDelete] = useState(null)

  const load = useCallback(async () => {
    try {
      const { data: cameraData } = await api.get('/api/cameras')
      setCameras(cameraData.cameras)
      setSummary(cameraData.summary)
      setError('')
    } catch (requestError) {
      setError(apiError(requestError))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const timer = setInterval(load, 30000)
    return () => clearInterval(timer)
  }, [load])

  const change = (key) => (event) => {
    const value =
      event.target.type === 'checkbox' ? event.target.checked : event.target.value
    setForm((current) => ({ ...current, [key]: value }))
  }

  const openCreate = () => {
    setEditing(null)
    setForm({ ...EMPTY_FORM, camera_id: `CAM-0${cameras.length + 1}` })
    setFormError('')
    setTestResult(null)
    setModalOpen(true)
  }

  const openEdit = (camera) => {
    setEditing(camera)
    setForm({
      ...EMPTY_FORM,
      ...camera,
      mode: 'LIVE',
      password: '',
      demo_source_type: '',
      demo_source_path: '',
    })
    setFormError('')
    setTestResult(null)
    setModalOpen(true)
  }

  const save = async (event) => {
    event.preventDefault()
    setSaving(true)
    setFormError('')
    try {
      const payload = {
        ...form,
        mode: 'LIVE',
        demo_source_type: '',
        demo_source_path: '',
      }
      if (editing) {
        delete payload.camera_id
        if (!payload.password) delete payload.password
        await api.put(`/api/cameras/${editing.camera_id}`, payload)
        toast.success(`${editing.camera_id} updated`)
      } else {
        await api.post('/api/cameras', payload)
        toast.success(`${form.camera_id} added and started`)
      }
      setModalOpen(false)
      load()
    } catch (requestError) {
      setFormError(apiError(requestError))
    } finally {
      setSaving(false)
    }
  }

  const testConfiguration = async () => {
    setTesting('form')
    setTestResult(null)
    try {
      const { data } = await api.post('/api/cameras/test-config', form)
      setTestResult(data)
    } catch (requestError) {
      setTestResult({ ok: false, message: apiError(requestError) })
    } finally {
      setTesting('')
    }
  }

  const testCamera = async (camera) => {
    setTesting(camera.camera_id)
    try {
      const { data } = await api.post(`/api/cameras/${camera.camera_id}/test`)
      if (data.ok) {
        toast.success(`${camera.camera_id}: ${data.message} (${data.resolution})`)
      } else {
        toast.error(`${camera.camera_id}: ${data.message}`)
      }
    } catch (requestError) {
      toast.error(apiError(requestError))
    } finally {
      setTesting('')
    }
  }

  const toggle = async (camera) => {
    try {
      await api.post(`/api/cameras/${camera.camera_id}/toggle`, { enabled: !camera.enabled })
      toast.success(`${camera.camera_id} ${camera.enabled ? 'disabled' : 'enabled'}`)
      load()
    } catch (requestError) {
      toast.error(apiError(requestError))
    }
  }

  const restart = async (camera) => {
    try {
      await api.post(`/api/cameras/${camera.camera_id}/restart`)
      toast.success(`${camera.camera_id} capture thread restarted`)
      load()
    } catch (requestError) {
      toast.error(apiError(requestError))
    }
  }

  const remove = async () => {
    try {
      await api.delete(`/api/cameras/${confirmDelete.camera_id}`)
      toast.success(`${confirmDelete.camera_id} deleted`)
      setConfirmDelete(null)
      load()
    } catch (requestError) {
      toast.error(apiError(requestError))
    }
  }

  if (loading) return <Loader label="Loading cameras..." />

  return (
    <>
      <PageHeader
        title="Cameras"
        description="Register real-time IP / RTSP cameras and test connectivity."
        actions={
          <>
            <button type="button" className="btn-secondary btn-sm" onClick={load}>
              <RefreshCw size={14} /> Refresh
            </button>
            {isAdmin && (
              <button type="button" className="btn-primary btn-sm" onClick={openCreate}>
                <Plus size={15} /> Add Camera
              </button>
            )}
          </>
        }
      />

      {error && <div className="mb-4"><ErrorNote message={error} /></div>}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Total cameras" value={summary.total ?? 0} icon={Cctv} tone="brand" />
        <StatCard label="Online" value={summary.online ?? 0} tone="green" icon={Plug} />
        <StatCard
          label="Offline"
          value={summary.offline ?? 0}
          tone={summary.offline ? 'red' : 'slate'}
          icon={Power}
        />
        <StatCard
          label="Live cameras"
          value={summary.live_mode ?? cameras.filter((c) => c.mode === 'LIVE').length}
          tone="amber"
          icon={RotateCw}
        />
      </div>

      <div className="mt-5">
        <Card title="Registered cameras" bodyClass="p-0">
          {cameras.length === 0 ? (
            <EmptyState
              icon={Cctv}
              title="No cameras registered"
              description="Add your first camera to start monitoring."
              action={
                isAdmin && (
                  <button type="button" className="btn-primary btn-sm" onClick={openCreate}>
                    <Plus size={15} /> Add Camera
                  </button>
                )
              }
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Camera</th>
                    <th>Stream</th>
                    <th>Network</th>
                    <th>Status</th>
                    <th>Health</th>
                    <th className="text-right">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {cameras.map((camera) => (
                    <tr key={camera.camera_id}>
                      <td>
                        <p className="font-semibold text-slate-800">{camera.camera_id}</p>
                        <p className="text-xs text-slate-600">{camera.name}</p>
                        <p className="max-w-[16rem] truncate text-xs text-slate-500">
                          {camera.location || 'Location not set'}
                        </p>
                      </td>
                      <td>
                        <Pill status="LIVE" label="LIVE" />
                        <p className="mt-1 max-w-[15rem] truncate text-xs text-slate-500">
                          {camera.stream_source || camera.rtsp_url || 'No RTSP URL'}
                        </p>
                      </td>
                      <td className="text-xs">
                        <p className="font-mono text-slate-700">{camera.ip_address || '-'}</p>
                        <p className="text-slate-500">
                          {camera.password_set ? 'Credentials stored' : 'No credentials'}
                        </p>
                      </td>
                      <td>
                        <Pill status={camera.health?.status || 'CONNECTING'} />
                        {!camera.enabled && (
                          <p className="mt-1 text-xs text-slate-500">Disabled</p>
                        )}
                      </td>
                      <td className="text-xs">
                        <p className="text-slate-700">
                          {(camera.health?.fps ?? 0).toFixed(1)} FPS ·{' '}
                          {camera.health?.violation_count ?? 0} violations
                        </p>
                        <p className="text-slate-500">
                          Last frame {timeAgo(camera.health?.last_frame_at)}
                        </p>
                        {camera.health?.connection_error && (
                          <p className="mt-0.5 max-w-[18rem] truncate text-rose-600">
                            {camera.health.connection_error}
                          </p>
                        )}
                      </td>
                      <td>
                        <div className="flex flex-wrap items-center justify-end gap-1.5">
                          <button
                            type="button"
                            className="btn-secondary btn-sm"
                            onClick={() => testCamera(camera)}
                            disabled={testing === camera.camera_id}
                          >
                            <Plug size={13} />
                            {testing === camera.camera_id ? 'Testing' : 'Test'}
                          </button>
                          {isAdmin && (
                            <>
                              <button
                                type="button"
                                className="btn-secondary btn-sm"
                                onClick={() => openEdit(camera)}
                              >
                                <Pencil size={13} /> Edit
                              </button>
                              <button
                                type="button"
                                className="btn-secondary btn-sm"
                                onClick={() => toggle(camera)}
                              >
                                <Power size={13} />
                                {camera.enabled ? 'Disable' : 'Enable'}
                              </button>
                              <button
                                type="button"
                                className="btn-secondary btn-sm"
                                onClick={() => restart(camera)}
                                title="Restart the capture thread"
                              >
                                <RotateCw size={13} />
                              </button>
                              <button
                                type="button"
                                className="btn-danger btn-sm"
                                onClick={() => setConfirmDelete(camera)}
                              >
                                <Trash2 size={13} />
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      {!isAdmin && (
        <div className="mt-4">
          <InfoNote tone="slate">
            You are signed in as a Traffic Officer. Camera configuration is restricted to
            Administrator accounts; you can still test connectivity.
          </InfoNote>
        </div>
      )}

      {/* ---------------- add / edit modal ---------------- */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editing ? `Edit ${editing.camera_id}` : 'Add Camera'}
        subtitle={
          editing
            ? 'Saving restarts this camera capture thread only.'
            : 'The camera starts streaming as soon as it is saved.'
        }
        size="lg"
        footer={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={testConfiguration}
              disabled={testing === 'form'}
            >
              <Plug size={15} />
              {testing === 'form' ? 'Testing...' : 'Test Connection'}
            </button>
            <button type="button" className="btn-ghost" onClick={() => setModalOpen(false)}>
              Cancel
            </button>
            <button type="submit" form="camera-form" className="btn-primary" disabled={saving}>
              {saving ? 'Saving...' : editing ? 'Save changes' : 'Add camera'}
            </button>
          </>
        }
      >
        <form id="camera-form" onSubmit={save} className="space-y-4">
          {formError && <ErrorNote message={formError} />}

          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Camera Name" required>
              <input
                className="input"
                value={form.name}
                onChange={change('name')}
                placeholder="Camera 1"
                required
              />
            </Field>
            <Field label="Camera ID" required hint={editing ? 'Camera ID cannot be changed.' : 'Unique code, e.g. CAM-01'}>
              <input
                className="input"
                value={form.camera_id}
                onChange={change('camera_id')}
                placeholder="CAM-01"
                disabled={Boolean(editing)}
                required
              />
            </Field>
            <Field label="IP Address / host:port" hint="IP Webcam example: 10.0.0.5:8080">
              <input
                className="input font-mono"
                value={form.ip_address}
                onChange={change('ip_address')}
                placeholder="10.157.212.237:8080"
              />
            </Field>
            <Field
              label="Stream URL"
              hint="IP Webcam: http://IP:8080/video — or leave blank to auto-build from IP."
            >
              <input
                className="input font-mono text-xs"
                value={form.rtsp_url}
                onChange={change('rtsp_url')}
                placeholder="http://10.157.212.237:8080/video"
              />
            </Field>
            <Field label="Username">
              <input
                className="input"
                value={form.username}
                onChange={change('username')}
                placeholder="admin"
                autoComplete="off"
              />
            </Field>
            <Field
              label="Password"
              hint={editing ? 'Leave blank to keep the stored password.' : 'Stored on the server only.'}
            >
              <input
                className="input"
                type="password"
                value={form.password}
                onChange={change('password')}
                autoComplete="new-password"
              />
            </Field>
            <Field label="Location">
              <input
                className="input"
                value={form.location}
                onChange={change('location')}
                placeholder="MG Road Junction - North Approach"
              />
            </Field>
            <Field label="Frame rate" hint="Every camera is set to 30 FPS.">
              <input className="input" value="30 FPS" readOnly />
            </Field>
            <Field label="Permitted traffic direction" hint="Used for the wrong-side driving check.">
              <select
                className="input"
                value={form.allowed_direction}
                onChange={change('allowed_direction')}
              >
                {DIRECTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </Field>
          </div>

          <Field label="Description">
            <textarea
              className="input h-20"
              value={form.description}
              onChange={change('description')}
              placeholder="Main signal junction, covers both two-wheeler lanes."
            />
          </Field>

          <div className="rounded-lg border border-brand-200 bg-brand-50 p-4">
            <p className="text-sm font-semibold text-slate-800">IP Webcam / LIVE stream</p>
            <p className="mt-1 text-xs text-slate-600">
              For the Android IP Webcam app, start the server on your phone, then use
              host:port (e.g. 192.168.x.x:8080) or http://IP:8080/video. Username/password
              match the app&apos;s login settings.
            </p>
          </div>

          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input type="checkbox" checked={form.enabled} onChange={change('enabled')} />
              Camera enabled
            </label>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={form.detection_enabled}
                onChange={change('detection_enabled')}
              />
              Run AI violation detection on this camera
            </label>
          </div>

          {testResult && (
            <div
              className={`rounded-lg border px-3.5 py-2.5 text-sm ${
                testResult.ok
                  ? 'border-emerald-200 bg-emerald-50 text-emerald-800'
                  : 'border-rose-200 bg-rose-50 text-rose-800'
              }`}
            >
              <p className="font-semibold">
                {testResult.ok ? 'Connection successful' : 'Connection failed'}
              </p>
              <p className="mt-0.5">{testResult.message}</p>
              {testResult.resolution && (
                <p className="mt-0.5 text-xs">
                  Resolution {testResult.resolution} · {testResult.latency_ms} ms ·{' '}
                  {testResult.source}
                </p>
              )}
            </div>
          )}
        </form>
      </Modal>

      {/* ---------------- delete confirmation ---------------- */}
      <Modal
        open={Boolean(confirmDelete)}
        onClose={() => setConfirmDelete(null)}
        title={`Delete ${confirmDelete?.camera_id}?`}
        size="sm"
        footer={
          <>
            <button type="button" className="btn-ghost" onClick={() => setConfirmDelete(null)}>
              Cancel
            </button>
            <button type="button" className="btn-danger" onClick={remove}>
              <Trash2 size={15} /> Delete camera
            </button>
          </>
        }
      >
        <p className="text-sm text-slate-600">
          The capture thread stops immediately and the camera is removed from the database.
          Violations and challans already recorded for this camera are kept.
        </p>
      </Modal>
    </>
  )
}
