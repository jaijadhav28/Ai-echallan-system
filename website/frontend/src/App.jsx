import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import { Loader } from './components/ui'
import { useAuth } from './context/AuthContext'

const Dashboard = lazy(() => import('./pages/Dashboard'))
const LiveMonitoring = lazy(() => import('./pages/LiveMonitoring'))
const Cameras = lazy(() => import('./pages/Cameras'))
const Violations = lazy(() => import('./pages/Violations'))
const Challans = lazy(() => import('./pages/Challans'))
const Vehicles = lazy(() => import('./pages/Vehicles'))
const Reports = lazy(() => import('./pages/Reports'))
const NetworkStatus = lazy(() => import('./pages/NetworkStatus'))
const NotFound = lazy(() => import('./pages/NotFound'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const MaintenanceAlerts = lazy(() => import('./pages/MaintenanceAlerts'))
const Settings = lazy(() => import('./pages/Settings'))
const Users = lazy(() => import('./pages/Users'))
const ViolationRules = lazy(() => import('./pages/ViolationRules'))

function PageFallback() {
  return <Loader label="Loading page..." className="min-h-[40vh]" />
}

function RequireAuth({ children, adminOnly = false }) {
  const { isAuthenticated, isAdmin, loading } = useAuth()
  if (loading) return <Loader label="Restoring your session..." className="min-h-screen" />
  if (!isAuthenticated) return <Navigate to="/login" replace />
  if (adminOnly && !isAdmin) return <Navigate to="/dashboard" replace />
  return children
}

export default function App() {
  const { isAuthenticated, loading } = useAuth()

  return (
    <Suspense fallback={<PageFallback />}>
      <Routes>
        <Route
          path="/login"
          element={
            loading ? (
              <Loader label="Loading..." className="min-h-screen" />
            ) : isAuthenticated ? (
              <Navigate to="/dashboard" replace />
            ) : (
              <Login />
            )
          }
        />
        <Route
          path="/register"
          element={
            loading ? (
              <Loader label="Loading..." className="min-h-screen" />
            ) : isAuthenticated ? (
              <Navigate to="/dashboard" replace />
            ) : (
              <Register />
            )
          }
        />

        <Route
          element={
            <RequireAuth>
              <Layout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="/dashboard" element={<Dashboard />} />
          <Route path="/live" element={<LiveMonitoring />} />
          <Route path="/cameras" element={<Cameras />} />
          <Route path="/violations" element={<Violations />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/network" element={<NetworkStatus />} />
          <Route path="/alerts" element={<MaintenanceAlerts />} />
          <Route path="/rules" element={<ViolationRules />} />
          <Route path="/settings" element={<Settings />} />
          <Route
            path="/users"
            element={
              <RequireAuth adminOnly>
                <Users />
              </RequireAuth>
            }
          />
          <Route path="/challans" element={<Challans />} />
          <Route path="/vehicles" element={<Vehicles />} />
          <Route path="/api-configuration" element={<Navigate to="/settings" replace />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  )
}
