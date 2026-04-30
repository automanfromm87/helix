import { useEffect, useMemo, useState } from 'react'
import { Eye, EyeOff, LoaderCircle } from 'lucide-react'

import { useAuth } from '@/hooks/useAuth'
import { validateUserInput } from '@/utils/auth'
import { showErrorToast, showSuccessToast } from '@/utils/toast'
import { getCachedAuthProvider } from '@/api/config'
import { cn } from '@/lib/utils'

interface Props {
  onSuccess: () => void
  onSwitchToRegister: () => void
  onSwitchToReset: () => void
}

export default function LoginForm({ onSuccess, onSwitchToRegister, onSwitchToReset }: Props) {
  const { login, isLoading, authError } = useAuth()
  const [hasRegister, setHasRegister] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})

  useEffect(() => {
    void getCachedAuthProvider().then((p) => setHasRegister(p === 'password'))
  }, [])

  const validateField = (field: 'email' | 'password') => {
    const result = validateUserInput({ [field]: field === 'email' ? email : password } as any)
    setErrors((prev) => ({ ...prev, [field]: result.errors[field] ?? '' }))
  }

  const isFormValid = useMemo(() => {
    if (!email.trim() || !password.trim()) return false
    return !errors.email && !errors.password
  }, [email, password, errors])

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const result = validateUserInput({ email, password })
    if (!result.isValid) {
      setErrors(result.errors)
      return
    }
    try {
      await login({ email, password })
      showSuccessToast('Login successful! Welcome back')
      onSuccess()
    } catch (e) {
      console.error('Login failed:', e)
      showErrorToast(authError || 'Login failed, please try again')
    }
  }

  return (
    <div className="w-full max-w-[384px] py-[24px] pt-0 px-[12px] relative z-[1]">
      <div className="flex flex-col justify-center gap-[40px] text-[var(--text-primary)] max-sm:gap-[12px]">
        <form onSubmit={handleSubmit} className="flex flex-col items-stretch gap-[20px]">
          <div className="flex flex-col gap-[12px]">
            <div className="flex flex-col items-start">
              <div className="w-full flex items-center justify-between gap-[12px] mb-[8px]">
                <label htmlFor="email" className="text-[13px] font-medium">
                  Email <span className="text-[var(--function-error)]">*</span>
                </label>
              </div>
              <input
                id="email"
                type="email"
                placeholder="mail@domain.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                onBlur={() => validateField('email')}
                disabled={isLoading}
                className={cn(
                  'rounded-[10px] text-sm text-[var(--text-primary)] h-10 w-full bg-[var(--fill-input-chat)] pt-1 pr-1.5 pb-1 pl-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none placeholder:text-[var(--text-disable)]',
                  errors.email && 'ring-1 ring-[var(--function-error)]',
                )}
              />
              {errors.email && (
                <div className="text-[13px] text-[var(--function-error)] mt-[2px]">{errors.email}</div>
              )}
            </div>

            <div className="flex flex-col items-start">
              <div className="w-full flex items-center justify-between gap-[12px] mb-[8px]">
                <label htmlFor="password" className="text-[13px] font-medium">
                  Password <span className="text-[var(--function-error)]">*</span>
                </label>
                <span
                  className="underline text-[var(--text-tertiary)] text-[13px] cursor-pointer hover:opacity-80"
                  onClick={onSwitchToReset}
                >
                  Forgot Password?
                </span>
              </div>
              <div className="relative w-full">
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Enter password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  onBlur={() => validateField('password')}
                  disabled={isLoading}
                  className={cn(
                    'rounded-[10px] text-sm text-[var(--text-primary)] h-10 w-full bg-[var(--fill-input-chat)] pt-1 pb-1 pl-3 pr-[40px] focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none placeholder:text-[var(--text-disable)]',
                    errors.password && 'ring-1 ring-[var(--function-error)]',
                  )}
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="text-[var(--icon-tertiary)] absolute z-30 right-[6px] top-1/2 p-[6px] rounded-md -translate-y-1/2 hover:text-[var(--icon-primary)]"
                >
                  {showPassword ? <Eye size={16} /> : <EyeOff size={16} />}
                </button>
              </div>
              {errors.password && (
                <div className="text-[13px] text-[var(--function-error)] mt-[2px]">{errors.password}</div>
              )}
            </div>

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
              {isLoading ? 'Processing...' : 'Login'}
            </button>
          </div>

          {hasRegister && (
            <div className="text-center text-[13px] text-[var(--text-tertiary)] mt-[8px]">
              <span>Don't have an account?</span>
              <span
                onClick={onSwitchToRegister}
                className="ms-[8px] text-[var(--text-secondary)] cursor-pointer hover:opacity-80 underline"
              >
                Register
              </span>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}
