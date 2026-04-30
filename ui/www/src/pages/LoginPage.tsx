import { useEffect, useState } from 'react'
import { Bot } from 'lucide-react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import LoginForm from '@/components/login/LoginForm'
import RegisterForm from '@/components/login/RegisterForm'
import ResetPasswordForm from '@/components/login/ResetPasswordForm'
import { HelixLogoTextIcon } from '@/components/icons'
import { useAuth } from '@/hooks/useAuth'

type Mode = 'login' | 'register' | 'reset'

export default function LoginPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const { isAuthenticated } = useAuth()
  const [mode, setMode] = useState<Mode>('login')

  const goNext = () => {
    const redirect = searchParams.get('redirect')
    navigate(redirect || '/')
  }

  useEffect(() => {
    if (isAuthenticated) goNext()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated])

  return (
    <div className="w-full min-h-[100vh] relative bg-[var(--background-gray-main)] dark:bg-[#050505]">
      <div className="sticky top-0 left-0 w-full z-10 px-[48px] max-sm:px-[12px]">
        <div className="w-full h-[60px] mx-auto flex items-center justify-between text-[var(--text-primary)]">
          <a href="/">
            <div className="flex">
              <Bot size={30} />
              <HelixLogoTextIcon />
            </div>
          </a>
        </div>
      </div>
      <div className="relative z-[1] flex flex-col justify-center items-center min-h-[100vh] pt-[20px] pb-[60px] -mt-[60px]">
        <div className="w-full max-w-[720px] pt-[24px] mb-[40px]">
          <div className="flex flex-col items-center gap-[20px] relative z-[1]">
            <div className="w-[80px] h-[80px] text-[var(--icon-primary)] max-sm:w-[64px] max-sm:h-[64px]">
              <Bot size={80} />
            </div>
            <h1 className="text-[20px] font-bold text-center text-[var(--text-primary)] max-sm:text-[18px]">
              {mode === 'reset'
                ? 'Reset Password'
                : mode === 'register'
                ? 'Register to Helix'
                : 'Login to Helix'}
            </h1>
          </div>
        </div>
        {mode === 'login' && (
          <LoginForm
            onSuccess={goNext}
            onSwitchToRegister={() => setMode('register')}
            onSwitchToReset={() => setMode('reset')}
          />
        )}
        {mode === 'register' && (
          <RegisterForm onSuccess={goNext} onSwitchToLogin={() => setMode('login')} />
        )}
        {mode === 'reset' && <ResetPasswordForm onBackToLogin={() => setMode('login')} />}
      </div>
    </div>
  )
}
