import { useMemo, useState } from 'react'
import { Eye, EyeOff, LoaderCircle } from 'lucide-react'

import { useAuth } from '@/hooks/useAuth'
import { validateUserInput } from '@/utils/auth'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { cn } from '@/lib/utils'

interface Props {
  onSuccess: () => void
  onSwitchToLogin: () => void
}

export default function RegisterForm({ onSuccess, onSwitchToLogin }: Props) {
  const { register, isLoading, authError } = useAuth()
  const [showPassword, setShowPassword] = useState(false)
  const [fullname, setFullname] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const isFormValid = useMemo(() => {
    if (!fullname.trim() || !email.trim() || !password || !confirm) return false
    if (password !== confirm) return false
    return Object.values(errors).every((v) => !v)
  }, [fullname, email, password, confirm, errors])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const result = validateUserInput({ fullname, email, password })
    if (password !== confirm) {
      result.errors.confirm = 'Passwords do not match'
    }
    setErrors(result.errors)
    if (!result.isValid || password !== confirm) return

    try {
      await register({ fullname, email, password })
      showSuccessToast('Registration successful! Welcome to Helix')
      onSuccess()
    } catch (e) {
      console.error('Register failed:', e)
      showErrorToast(authError || 'Authentication failed, please try again')
    }
  }

  const Field = ({
    id,
    label,
    type,
    value,
    onChange,
    placeholder,
    error,
  }: {
    id: string
    label: string
    type: string
    value: string
    onChange: (v: string) => void
    placeholder: string
    error?: string
  }) => (
    <div className="flex flex-col items-start">
      <label htmlFor={id} className="text-[13px] font-medium mb-[8px]">
        {label} <span className="text-[var(--function-error)]">*</span>
      </label>
      <input
        id={id}
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        disabled={isLoading}
        className={cn(
          'rounded-[10px] text-sm text-[var(--text-primary)] h-10 w-full bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none placeholder:text-[var(--text-disable)]',
          error && 'ring-1 ring-[var(--function-error)]',
        )}
      />
      {error && <div className="text-[13px] text-[var(--function-error)] mt-[2px]">{error}</div>}
    </div>
  )

  return (
    <div className="w-full max-w-[384px] py-[24px] pt-0 px-[12px] relative z-[1]">
      <form onSubmit={handleSubmit} className="flex flex-col items-stretch gap-[20px]">
        <div className="flex flex-col gap-[12px]">
          <Field
            id="fullname"
            label="Full Name"
            type="text"
            value={fullname}
            onChange={setFullname}
            placeholder="Enter your full name"
            error={errors.fullname}
          />
          <Field
            id="email"
            label="Email"
            type="email"
            value={email}
            onChange={setEmail}
            placeholder="mail@domain.com"
            error={errors.email}
          />
          <div className="flex flex-col items-start">
            <label htmlFor="password" className="text-[13px] font-medium mb-[8px]">
              Password <span className="text-[var(--function-error)]">*</span>
            </label>
            <div className="relative w-full">
              <input
                id="password"
                type={showPassword ? 'text' : 'password'}
                placeholder="Enter password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={isLoading}
                className={cn(
                  'rounded-[10px] text-sm h-10 w-full bg-[var(--fill-input-chat)] px-3 pr-[40px] focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none',
                  errors.password && 'ring-1 ring-[var(--function-error)]',
                )}
              />
              <button
                type="button"
                onClick={() => setShowPassword(!showPassword)}
                className="text-[var(--icon-tertiary)] absolute right-[6px] top-1/2 p-[6px] rounded-md -translate-y-1/2 hover:text-[var(--icon-primary)]"
              >
                {showPassword ? <Eye size={16} /> : <EyeOff size={16} />}
              </button>
            </div>
            {errors.password && (
              <div className="text-[13px] text-[var(--function-error)] mt-[2px]">{errors.password}</div>
            )}
          </div>
          <Field
            id="confirm"
            label="Confirm Password"
            type={showPassword ? 'text' : 'password'}
            value={confirm}
            onChange={setConfirm}
            placeholder="Enter password again"
            error={errors.confirm}
          />

          <button
            type="submit"
            disabled={!isFormValid || isLoading}
            className={cn(
              'inline-flex items-center justify-center whitespace-nowrap font-medium transition-colors h-[40px] px-[16px] rounded-[10px] gap-[6px] text-sm w-full',
              isFormValid && !isLoading
                ? 'bg-[var(--Button-primary-black)] text-[var(--text-onblack)] hover:opacity-90'
                : 'bg-[#898988] text-[var(--text-onblack)] opacity-50 cursor-not-allowed',
            )}
          >
            {isLoading && <LoaderCircle size={16} className="animate-spin" />}
            {isLoading ? 'Processing...' : 'Register'}
          </button>
        </div>

        <div className="text-center text-[13px] text-[var(--text-tertiary)] mt-[8px]">
          <span>Already have an account?</span>
          <span
            onClick={onSwitchToLogin}
            className="ms-[8px] text-[var(--text-secondary)] cursor-pointer hover:opacity-80 underline"
          >
            Login
          </span>
        </div>
      </form>
    </div>
  )
}
