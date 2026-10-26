import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  CheckSquare,
  Eye,
  EyeOff,
  FileText,
  Loader2,
  Shield,
  Square,
} from 'lucide-react'
import api, { apiError } from '../lib/api'
import { useAuth } from '../context/AuthContext'
import { useToast } from '../context/ToastContext'
import { ErrorNote, Field } from '../components/ui'

function StrengthItem({ ok, label }) {
  return (
    <li className={`flex items-center gap-2 text-xs ${ok ? 'text-emerald-700' : 'text-slate-500'}`}>
      {ok ? (
        <CheckSquare size={14} className="shrink-0 text-emerald-600" />
      ) : (
        <Square size={14} className="shrink-0 text-slate-400" />
      )}
      {label}
    </li>
  )
}

export default function Register() {
  const navigate = useNavigate()
  const toast = useToast()
  const { applySessionFromRegister } = useAuth()

  const [name, setName] = useState('')
  const [batchId, setBatchId] = useState('')
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [otp, setOtp] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [otpInfo, setOtpInfo] = useState(null)
  const [busy, setBusy] = useState(false)
  const [otpBusy, setOtpBusy] = useState(false)
  const [error, setError] = useState('')

  const rules = useMemo(
    () => ({
      length: password.length >= 8,
      lower: /[a-z]/.test(password),
      upper: /[A-Z]/.test(password),
      number: /[0-9]/.test(password),
      special: /[@$!%*?&#]/.test(password),
    }),
    [password],
  )
  const strong = Object.values(rules).every(Boolean)

  const sendOtp = async () => {
    setError('')
    const digits = phone.replace(/\D/g, '').slice(-10)
    if (digits.length !== 10) {
      setError('Enter a valid 10-digit mobile number')
      return
    }
    setOtpBusy(true)
    try {
      const { data } = await api.post('/api/auth/register/otp', { phone: digits })
      setOtpInfo(data)
      if (data.sent) {
        toast.success(data.message)
      } else {
        toast.error(data.message || 'Could not send OTP')
      }
    } catch (requestError) {
      setError(apiError(requestError))
    } finally {
      setOtpBusy(false)
    }
  }

  const submit = async (event) => {
    event.preventDefault()
    setError('')
    if (!strong) {
      setError('Password does not meet all strength requirements')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match')
      return
    }
    if (!/^[A-Za-z0-9_\-]{3,30}$/.test(batchId.trim())) {
      setError('Officer Batch ID must be 3–30 letters, numbers, _ or -')
      return
    }
    if (otp.trim().length !== 6) {
      setError('Enter the 6-digit mobile verification OTP')
      return
    }

    setBusy(true)
    try {
      const { data } = await api.post('/api/auth/register', {
        name: name.trim(),
        batch_id: batchId.trim(),
        phone: phone.replace(/\D/g, '').slice(-10),
        password,
        otp: otp.trim(),
      })
      applySessionFromRegister(data)
      toast.success('Account created successfully')
      navigate('/dashboard', { replace: true })
    } catch (requestError) {
      setError(apiError(requestError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <div className="relative hidden flex-col justify-between bg-navy-900 px-12 py-12 text-white lg:flex">
        <div>
          <div className="flex items-center gap-3">
            <span className="grid h-12 w-12 place-items-center rounded-xl bg-brand-600 font-bold">
              RTO
            </span>
            <div>
              <p className="text-lg font-semibold leading-tight">Regional Transport Office</p>
              <p className="text-sm text-slate-400">Traffic Enforcement Portal</p>
            </div>
          </div>

          <h1 className="mt-14 max-w-xl text-3xl font-semibold leading-snug">
            Create your officer account
            <span className="block text-brand-400">for the E-Challan System</span>
          </h1>
          <p className="mt-4 max-w-lg text-sm leading-relaxed text-slate-300">
            Register with your Officer Batch ID and mobile number. After OTP verification you can
            monitor cameras, review violations and manage challans.
          </p>
        </div>

        <p className="text-xs text-slate-500">
          Authorised personnel only. All registration attempts are logged.
        </p>
      </div>

      <div className="flex items-start justify-center bg-slate-100 px-4 py-8 sm:px-8 sm:py-10">
        <div className="w-full max-w-md">
          <div className="mb-6 flex items-center gap-3 lg:hidden">
            <span className="grid h-11 w-11 place-items-center rounded-xl bg-brand-600 font-bold text-white">
              RTO
            </span>
            <div>
              <p className="font-semibold text-slate-900">RTO E-Challan System</p>
              <p className="text-xs text-slate-500">Create officer account</p>
            </div>
          </div>

          <div className="card p-6 sm:p-7">
            <div className="mb-5 text-center sm:text-left">
              <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-brand-600 text-white shadow-sm sm:mx-0">
                <Shield size={24} strokeWidth={2.25} />
              </div>
              <h2 className="text-lg font-semibold text-slate-900">Create Your Account</h2>
              <p className="mt-1 text-sm text-slate-500">
                Register to link vehicles and pay challans securely
              </p>
              <div className="mt-4 h-px w-full bg-slate-200" />
            </div>

            {error && (
              <div className="mb-4">
                <ErrorNote message={error} />
              </div>
            )}

            <form onSubmit={submit} className="space-y-4">
              <Field label="Full Name" required>
                <input
                  className="input"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="e.g. Ramesh Kumar"
                  required
                  minLength={2}
                />
              </Field>

              <Field
                label="Officer Batch ID Number"
                hint="This will be your permanent Officer Batch ID Number to log in."
                required
              >
                <input
                  className="input"
                  value={batchId}
                  onChange={(event) => setBatchId(event.target.value.toUpperCase())}
                  placeholder="e.g. TP_BATCH_2026 / 10482 (alphanumeric, 3-30 chars)"
                  required
                  minLength={3}
                  maxLength={30}
                />
              </Field>

              <div>
                <Field
                  label="Mobile Number"
                  hint={
                    otpInfo?.masked_phone
                      ? `OTP sent to ${otpInfo.masked_phone}`
                      : "Click 'Send OTP' to verify your mobile number."
                  }
                  required
                >
                  <div className="flex gap-2">
                    <input
                      className="input min-w-0 flex-1"
                      value={phone}
                      onChange={(event) =>
                        setPhone(event.target.value.replace(/\D/g, '').slice(0, 10))
                      }
                      placeholder="10-digit mobile number"
                      inputMode="numeric"
                      required
                    />
                    <button
                      type="button"
                      onClick={sendOtp}
                      disabled={otpBusy || phone.length !== 10}
                      className="btn-secondary shrink-0"
                    >
                      {otpBusy ? <Loader2 size={16} className="animate-spin" /> : 'Send OTP'}
                    </button>
                  </div>
                </Field>
              </div>

              <Field label="Create Password" required>
                <div className="relative">
                  <input
                    className="input pr-16"
                    type={showPassword ? 'text' : 'password'}
                    value={password}
                    onChange={(event) => setPassword(event.target.value)}
                    placeholder="Enter strong password"
                    required
                    minLength={8}
                  />
                  <button
                    type="button"
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-brand-600 hover:text-brand-700"
                    onClick={() => setShowPassword((value) => !value)}
                  >
                    {showPassword ? (
                      <span className="inline-flex items-center gap-1">
                        <EyeOff size={14} /> Hide
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1">
                        <Eye size={14} /> Show
                      </span>
                    )}
                  </button>
                </div>
              </Field>

              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3.5 py-3">
                <p className="mb-2 text-xs font-semibold text-slate-600">Password strength</p>
                <ul className="grid grid-cols-1 gap-1.5 sm:grid-cols-2">
                  <StrengthItem ok={rules.length} label="Min 8 characters" />
                  <StrengthItem ok={rules.upper} label="Uppercase (A-Z)" />
                  <StrengthItem ok={rules.lower} label="Lowercase (a-z)" />
                  <StrengthItem ok={rules.number} label="Number (0-9)" />
                  <StrengthItem ok={rules.special} label="Special char (@$!%*?&#)" />
                </ul>
              </div>

              <Field label="Confirm Password" required>
                <div className="relative">
                  <input
                    className="input pr-16"
                    type={showConfirm ? 'text' : 'password'}
                    value={confirm}
                    onChange={(event) => setConfirm(event.target.value)}
                    placeholder="Re-enter password"
                    required
                    minLength={8}
                  />
                  <button
                    type="button"
                    className="absolute right-3 top-1/2 -translate-y-1/2 text-xs font-semibold text-brand-600 hover:text-brand-700"
                    onClick={() => setShowConfirm((value) => !value)}
                  >
                    {showConfirm ? (
                      <span className="inline-flex items-center gap-1">
                        <EyeOff size={14} /> Hide
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1">
                        <Eye size={14} /> Show
                      </span>
                    )}
                  </button>
                </div>
              </Field>

              <div className="rounded-xl border border-brand-200 bg-brand-50/60 p-4">
                <p className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-brand-700">
                  Enter 6-digit Mobile Verification OTP
                </p>
                <input
                  className="input text-center font-mono text-lg tracking-[0.35em]"
                  value={otp}
                  onChange={(event) => setOtp(event.target.value.replace(/\D/g, '').slice(0, 6))}
                  placeholder="••••••"
                  inputMode="numeric"
                  maxLength={6}
                  required
                />
                <button
                  type="button"
                  onClick={sendOtp}
                  disabled={otpBusy || phone.length !== 10}
                  className="mt-2 text-sm font-semibold text-brand-600 hover:text-brand-700 disabled:opacity-50"
                >
                  Resend OTP
                </button>
              </div>

              <button type="submit" className="btn-primary w-full" disabled={busy}>
                {busy ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
                Complete Registration
              </button>
            </form>

            <p className="mt-5 text-center text-sm text-slate-500">
              Already have an account?{' '}
              <Link to="/login" className="font-semibold text-brand-600 hover:text-brand-700">
                Login with User ID &amp; Password
              </Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
