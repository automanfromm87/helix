import { useEffect, useState } from 'react'
import { LoaderCircle } from 'lucide-react'

import { Dialog, DialogContent, DialogHeader, DialogTitle } from '../ui/Dialog'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../ui/Tabs'
import { useSettingsDialog } from '@/hooks/useSettingsDialog'
import { useAuth } from '@/hooks/useAuth'
import { changeFullname, changePassword } from '@/api/auth'
import { showErrorToast, showSuccessToast } from '@/utils/toast'

export default function SettingsDialog() {
  const isOpen = useSettingsDialog((s) => s.isOpen)
  const closeSettingsDialog = useSettingsDialog((s) => s.closeSettingsDialog)
  const defaultTab = useSettingsDialog((s) => s.defaultTab)

  const { currentUser, loadCurrentUser } = useAuth()
  const [name, setName] = useState(currentUser?.fullname ?? '')
  const [savingName, setSavingName] = useState(false)
  const [oldPassword, setOldPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)

  useEffect(() => {
    setName(currentUser?.fullname ?? '')
  }, [currentUser])

  const handleNameSave = async () => {
    if (!name.trim()) return
    setSavingName(true)
    try {
      await changeFullname({ fullname: name })
      showSuccessToast('Full name updated successfully')
      await loadCurrentUser()
    } catch {
      showErrorToast('Failed to update full name')
    } finally {
      setSavingName(false)
    }
  }

  const handlePasswordSave = async () => {
    if (!oldPassword || !newPassword) return
    setSavingPwd(true)
    try {
      await changePassword({ old_password: oldPassword, new_password: newPassword })
      showSuccessToast('Password change successful')
      setOldPassword('')
      setNewPassword('')
    } catch {
      showErrorToast('Password change failed')
    } finally {
      setSavingPwd(false)
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={(open) => (open ? null : closeSettingsDialog())}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Settings</DialogTitle>
        </DialogHeader>
        <Tabs defaultValue={defaultTab === 'account' ? 'account' : 'general'} className="w-full">
          <TabsList>
            <TabsTrigger value="general">General</TabsTrigger>
            <TabsTrigger value="account">Account</TabsTrigger>
          </TabsList>
          <TabsContent value="general">
            <div className="text-sm text-[var(--text-tertiary)] py-4">
              No general settings yet.
            </div>
          </TabsContent>
          <TabsContent value="account">
            <div className="flex flex-col gap-4 py-2">
              <div className="flex flex-col gap-2">
                <label className="text-[13px] font-medium">Name</label>
                <div className="flex gap-2">
                  <input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    className="flex-1 rounded-md text-sm h-9 bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
                  />
                  <button
                    onClick={handleNameSave}
                    disabled={savingName}
                    className="px-3 h-9 rounded-md bg-[var(--Button-primary-black)] text-[var(--text-onblack)] text-sm hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1"
                  >
                    {savingName && <LoaderCircle size={14} className="animate-spin" />}
                    Save
                  </button>
                </div>
              </div>

              <div className="flex flex-col gap-2">
                <label className="text-[13px] font-medium">Update Password</label>
                <input
                  type="password"
                  value={oldPassword}
                  onChange={(e) => setOldPassword(e.target.value)}
                  placeholder="Current Password"
                  className="rounded-md text-sm h-9 bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
                />
                <input
                  type="password"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="New Password"
                  className="rounded-md text-sm h-9 bg-[var(--fill-input-chat)] px-3 focus:ring-[1.5px] focus:ring-[var(--border-dark)] focus:outline-none"
                />
                <button
                  onClick={handlePasswordSave}
                  disabled={savingPwd}
                  className="self-start px-3 h-9 rounded-md bg-[var(--Button-primary-black)] text-[var(--text-onblack)] text-sm hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1"
                >
                  {savingPwd && <LoaderCircle size={14} className="animate-spin" />}
                  Update
                </button>
              </div>
            </div>
          </TabsContent>
        </Tabs>
      </DialogContent>
    </Dialog>
  )
}
