import { useState } from 'react'
import { ArrowLeft, LoaderCircle } from 'lucide-react'

import { resetPassword, sendVerificationCode } from '@/api/auth'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

interface Props {
  onBackToLogin: () => void
}

type Step = 'email' | 'verify'

export default function ResetPasswordForm({ onBackToLogin }: Props) {
  const [step, setStep] = useState<Step>('email')
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)

  const sendCode = async () => {
    if (!email.trim()) return
    setLoading(true)
    try {
      await sendVerificationCode({ email })
      showSuccessToast('Reset link sent to your email')
      setStep('verify')
    } catch {
      showErrorToast('Failed to send reset link. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const submitReset = async () => {
    if (newPassword !== confirm) {
      showErrorToast('Passwords do not match')
      return
    }
    if (!/^\d{6}$/.test(code)) {
      showErrorToast('Verification code must be 6 digits')
      return
    }
    setLoading(true)
    try {
      await resetPassword({ email, verification_code: code, new_password: newPassword })
      showSuccessToast('Password updated successfully')
      onBackToLogin()
    } catch {
      showErrorToast('Failed to update password. Please check your verification code and try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="w-full max-w-[384px] py-[24px] pt-0 px-[12px] relative z-[1]">
      {step === 'email' ? (
        <div className="flex flex-col gap-[20px]">
          <div className="flex flex-col gap-[12px]">
            <label htmlFor="reset-email" className="text-[13px] font-medium">
              Email
            </label>
            <input
              id="reset-email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="mail@domain.com"
              className="rounded-[10px] text-sm h-10 w-full bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
            />
            <button
              onClick={sendCode}
              disabled={!email.trim() || loading}
              className={cn(
                'inline-flex items-center justify-center font-medium h-[40px] rounded-[10px] gap-[6px] text-sm w-full',
                email.trim() && !loading
                  ? 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90'
                  : 'bg-[#898988] text-[var(--text-onblack)] opacity-50 cursor-not-allowed',
              )}
            >
              {loading && <LoaderCircle size={16} className="animate-spin" />}
              {loading ? 'Sending Code...' : 'Send Verification Code'}
            </button>
          </div>
          <button
            onClick={onBackToLogin}
            className="text-[13px] text-[var(--text-tertiary)] flex items-center gap-1 self-center hover:opacity-80"
          >
            <ArrowLeft size={14} /> Back to Login
          </button>
        </div>
      ) : (
        <div className="flex flex-col gap-[20px]">
          <div className="text-[13px] text-[var(--text-tertiary)]">
            Verification code sent to <span className="text-[var(--text-primary)]">{email}</span>
          </div>
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="Enter 6-digit verification code"
            className="rounded-[10px] text-sm h-10 w-full bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
          />
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="Enter your new password"
            className="rounded-[10px] text-sm h-10 w-full bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
          />
          <input
            type="password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            placeholder="Confirm your new password"
            className="rounded-[10px] text-sm h-10 w-full bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
          />
          <button
            onClick={submitReset}
            disabled={loading}
            className={cn(
              'inline-flex items-center justify-center font-medium h-[40px] rounded-[10px] gap-[6px] text-sm w-full',
              !loading
                ? 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90'
                : 'bg-[#898988] text-[var(--text-onblack)] opacity-50 cursor-not-allowed',
            )}
          >
            {loading && <LoaderCircle size={16} className="animate-spin" />}
            {loading ? 'Updating...' : 'Reset Password'}
          </button>
          <button
            onClick={onBackToLogin}
            className="text-[13px] text-[var(--text-tertiary)] flex items-center gap-1 self-center hover:opacity-80"
          >
            <ArrowLeft size={14} /> Back to Login
          </button>
        </div>
      )}
    </div>
  )
}
