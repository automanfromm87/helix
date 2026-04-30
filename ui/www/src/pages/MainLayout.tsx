import { useEffect } from 'react'
import { Outlet } from 'react-router-dom'

import LeftPanel from '@/components/LeftPanel'
import FilePanel from '@/components/FilePanel'
import TakeOverView from '@/components/TakeOverView'
import CustomDialog from '@/components/ui/CustomDialog'
import SessionFileList from '@/components/SessionFileList'
import SettingsDialog from '@/components/settings/SettingsDialog'
import ContextMenu from '@/components/ui/ContextMenu'
import CommandPalette from '@/components/CommandPalette'
import { useCommandPalette } from '@/hooks/useCommandPalette'

export default function MainLayout() {
  const togglePalette = useCommandPalette((s) => s.toggle)

  // Cmd/Ctrl+P opens the search palette. Cmd+K is reserved for "new chat".
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'p') {
        e.preventDefault()
        togglePalette()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [togglePalette])

  return (
    <>
      <div className="h-screen flex overflow-hidden bg-white">
        <LeftPanel />
        <div className="flex-1 min-w-0 h-full py-0 pr-0 relative">
          <div className="flex h-full bg-[var(--background-gray-main)]">
            <div className="flex flex-1 min-w-0 min-h-0">
              <Outlet />
              <FilePanel />
            </div>
          </div>
        </div>
      </div>
      <TakeOverView />
      <CustomDialog />
      <SessionFileList />
      <SettingsDialog />
      <ContextMenu />
      <CommandPalette />
    </>
  )
}
