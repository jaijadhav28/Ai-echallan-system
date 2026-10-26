import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  Camera,
  CameraOff,
  RefreshCw,
  ShieldAlert,
  Video,
} from 'lucide-react'
import api, { apiError, evidenceUrl } from '../lib/api'
import {
  Card,
  EmptyState,
  ErrorNote,
  Loader,
  PageHeader,
  Pill,
  StatCard,
} from '../components/ui'
import {
  VIOLATION_COLORS,
  confidencePercent,
  formatDateTime,
  timeAgo,
} from '../lib/format'

const REFRESH_MS = 60000

export default function Dashboard() {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [lastUpdated, setLastUpdated] = useState(null)

  const load = useCallback(
    async (showSpinner = false) => {
      if (showSpinner) setRefreshing(true)
      try {
        const { data: payload } = await api.get('/api/dashboard/summary', {
          params: { days: 7 },
          timeout: 8000,
        })
        setData(payload)
        setError('')
        setLastUpdated(new Date())
      } catch (requestError) {
        setError(apiError(requestError))
      } finally {
        if (showSpinner) setRefreshing(false)
      }
    },
    [],
  )

  useEffect(() => {
    load()
    const timer = setInterval(load, REFRESH_MS)
    return () => clearInterval(timer)
  }, [load])

  if (!data && error) return <ErrorNote message={error} />
  if (!data) return <Loader label="Loading dashboard..." />

  const { cards, charts, recent_violations: recent, pipeline } = data

  const cardItems = [
    {
      label: 'Total Cameras',
      value: cards.total_cameras,
      icon: Camera,
      tone: 'brand',
      hint: `${cards.active_cameras} active`,
    },
    {
      label: 'Active Cameras',
      value: cards.active_cameras,
      icon: Video,
      tone: 'green',
      hint: 'Streaming right now',
    },
    {
      label: 'Offline Cameras',
      value: cards.offline_cameras,
      icon: CameraOff,
      tone: cards.offline_cameras ? 'red' : 'slate',
      hint: cards.open_alerts ? `${cards.open_alerts} open alert(s)` : 'No open alerts',
    },
    {
      label: "Today's Violations",
      value: cards.todays_violations,
      icon: ShieldAlert,
      tone: 'amber',
      hint: `${cards.pending_review} awaiting review`,
    },
  ]

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Live enforcement overview across all connected cameras."
        actions={
          <>
            <span className="text-xs text-slate-500">
              Updated {lastUpdated ? timeAgo(lastUpdated.toISOString().slice(0, 19)) : '-'}
            </span>
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={() => load(true)}
              disabled={refreshing}
            >
              <RefreshCw size={14} className={refreshing ? 'animate-spin' : ''} /> Refresh
            </button>
          </>
        }
      />

      {error && (
        <div className="mb-4">
          <ErrorNote message={error} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {cardItems.map((item) => (
          <StatCard key={item.label} {...item} />
        ))}
      </div>

      <div className="mt-5 grid grid-cols-1 gap-5 xl:grid-cols-2">
        <Card
          title="Violations by type"
          subtitle="All recorded detections grouped by offence"
          bodyClass="p-4"
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={charts.violations_by_type} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 11, fill: '#64748b' }}
                interval={0}
                tickFormatter={(value) => (value.length > 14 ? `${value.slice(0, 13)}…` : value)}
              />
              <YAxis tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Bar dataKey="count" name="Violations" radius={[6, 6, 0, 0]}>
                {charts.violations_by_type.map((entry) => (
                  <Cell key={entry.code} fill={VIOLATION_COLORS[entry.code] || '#2456c4'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Daily activity"
          subtitle="Violations detected per day"
          bodyClass="p-4"
        >
          <ResponsiveContainer width="100%" height={260}>
            <LineChart data={charts.daily} margin={{ top: 8, right: 12, bottom: 4, left: -14 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: '#64748b' }}
                tickFormatter={(value) => value.slice(5)}
              />
              <YAxis tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="violations"
                name="Violations"
                stroke="#e11d48"
                strokeWidth={2}
                dot={{ r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </Card>

        <Card
          title="Camera activity"
          subtitle="Violations captured per camera"
          bodyClass="p-4"
          className="xl:col-span-2"
          actions={
            <Link to="/live" className="btn-secondary btn-sm">
              Open live monitoring
            </Link>
          }
        >
          <ResponsiveContainer width="100%" height={260}>
            <BarChart
              data={charts.camera_activity}
              layout="vertical"
              margin={{ top: 8, right: 16, bottom: 4, left: 10 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: '#64748b' }} allowDecimals={false} />
              <YAxis
                type="category"
                dataKey="camera_id"
                tick={{ fontSize: 11, fill: '#64748b' }}
                width={64}
              />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8 }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="violations" name="Total" fill="#2456c4" radius={[0, 6, 6, 0]} />
              <Bar dataKey="today" name="Today" fill="#f59e0b" radius={[0, 6, 6, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      </div>

      <div className="mt-5">
        <Card
          title="Recent violations"
          subtitle="Latest detections from all cameras"
          bodyClass="p-0"
          actions={
            <Link to="/violations" className="btn-secondary btn-sm">
              View all violations
            </Link>
          }
        >
          {recent.length === 0 ? (
            <EmptyState
              title="No violations recorded yet"
              description="Cameras are being monitored. Detections will appear here automatically."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="table">
                <thead>
                  <tr>
                    <th>Evidence</th>
                    <th>Detected</th>
                    <th>Camera</th>
                    <th>Violation</th>
                    <th>Vehicle</th>
                    <th>Confidence</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {recent.map((violation) => (
                    <tr key={violation.id}>
                      <td>
                        {violation.evidence_image ? (
                          <a
                            href={evidenceUrl(violation.evidence_image)}
                            target="_blank"
                            rel="noreferrer"
                          >
                            <img
                              src={evidenceUrl(violation.evidence_image)}
                              alt="Violation evidence"
                              className="h-11 w-20 rounded border border-slate-200 object-cover"
                              loading="lazy"
                            />
                          </a>
                        ) : (
                          <span className="text-xs text-slate-400">No image</span>
                        )}
                      </td>
                      <td className="whitespace-nowrap">
                        <p className="font-medium text-slate-800">
                          {formatDateTime(violation.detected_at)}
                        </p>
                        <p className="text-xs text-slate-500">{timeAgo(violation.detected_at)}</p>
                      </td>
                      <td className="whitespace-nowrap">
                        <p className="font-medium text-slate-800">{violation.camera_id}</p>
                        <p className="max-w-[14rem] truncate text-xs text-slate-500">
                          {violation.location || '-'}
                        </p>
                      </td>
                      <td>
                        <span className="font-medium text-slate-800">
                          {violation.violation_label}
                        </span>
                      </td>
                      <td className="whitespace-nowrap font-mono text-xs">
                        {violation.plate_number || '-'}
                      </td>
                      <td>{confidencePercent(violation.confidence)}</td>
                      <td>
                        <Pill status={violation.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>

      <p className="mt-4 text-xs text-slate-500">
        Detection pipeline: {pipeline.running ? 'running' : 'stopped'} · {pipeline.cycles} cycles ·{' '}
        {pipeline.violations_recorded} violations recorded
        {pipeline.last_error ? ` · last error: ${pipeline.last_error}` : ''}
      </p>
    </>
  )
}
