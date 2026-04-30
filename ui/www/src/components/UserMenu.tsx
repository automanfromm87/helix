import { useEffect, useState } from 'react'
import { LogOut, Settings2, User } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { useAuth } from '@/hooks/useAuth'
import { useSettingsDialog } from '@/hooks/useSettingsDialog'
import { getCachedAuthProvider } from '@/api/config'

export default function UserMenu() {
  const navigate = useNavigate()
  const { currentUser, logout } = useAuth()
  const openSettingsDialog = useSettingsDialog((s) => s.openSettingsDialog)
  const [authProvider, setAuthProvider] = useState<string | null>(null)

  useEffect(() => {
    void getCachedAuthProvider().then(setAuthProvider)
  }, [])

  const avatarLetter = currentUser?.fullname?.charAt(0)?.toUpperCase() || 'M'

  const handleLogout = async () => {
    try {
      await logout()
      navigate('/login')
    } catch (e) {
      console.error('Logout failed:', e)
    }
  }

  return (
    <div className="pointer-events-auto cursor-default">
      <div className="min-w-max inline-block transition-[transform,opacity,scale] duration-150">
        <div className="flex w-[300px] flex-col bg-[var(--background-menu-white)] rounded-[20px] border-[0.5px] border-[var(--border-dark)] shadow-[0px_8px_32px_0px_var(--shadow-XS)]">
          <div className="flex gap-2 px-4 pt-5 pb-3 w-full">
            <div className="relative flex items-center justify-center font-bold flex-shrink-0">
              <div
                className="relative flex items-center justify-center font-bold flex-shrink-0 rounded-full overflow-hidden"
                style={{
                  width: 48,
                  height: 48,
                  fontSize: 24,
                  color: 'rgba(255, 255, 255, 0.9)',
                  backgroundColor: 'rgb(59, 130, 246)',
                }}
              >
                {avatarLetter}
              </div>
            </div>
            <div className="flex overflow-hidden flex-col justify-center">
              <div className="flex gap-1 items-center w-full">
                <span className="text-[var(--text-primary)] text-base font-semibold leading-[22px] truncate">
                  {currentUser?.fullname || 'Unknown User'}
                </span>
              </div>
              <span className="text-[var(--text-tertiary)] text-[13px] font-normal leading-[18px] truncate">
                {currentUser?.email || 'No email'}
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-3 px-3 pb-3">
            <div className="flex flex-col gap-1">
              <div className="w-full h-px my-1 bg-[var(--border-main)]" />
              <div
                onClick={() => openSettingsDialog('account')}
                className="flex gap-3 items-center p-2 rounded-lg cursor-pointer text-[var(--text-primary)] hover:bg-[var(--fill-tsp-white-main)]"
              >
                <User size={20} />
                <span className="overflow-hidden flex-1 text-sm font-medium leading-5 whitespace-nowrap text-ellipsis">
                  Account
                </span>
              </div>
              <div
                onClick={() => openSettingsDialog('settings')}
                className="flex gap-3 items-center p-2 rounded-lg cursor-pointer text-[var(--text-primary)] hover:bg-[var(--fill-tsp-white-main)]"
              >
                <Settings2 size={20} />
                <span className="overflow-hidden flex-1 text-sm font-medium leading-5 whitespace-nowrap text-ellipsis">
                  Settings
                </span>
              </div>
              {authProvider !== 'none' && (
                <>
                  <div className="w-full h-px my-1 bg-[var(--border-main)]" />
                  <div
                    onClick={handleLogout}
                    className="flex gap-3 items-center p-2 rounded-lg cursor-pointer hover:bg-[var(--fill-tsp-white-main)] text-[var(--function-error)]"
                  >
                    <LogOut size={20} />
                    <span className="overflow-hidden flex-1 text-sm font-medium leading-5 whitespace-nowrap text-ellipsis">
                      Logout
                    </span>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
