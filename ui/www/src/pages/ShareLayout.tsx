import { Outlet } from 'react-router-dom'

import FilePanel from '@/components/FilePanel'
import CustomDialog from '@/components/ui/CustomDialog'
import SessionFileList from '@/components/SessionFileList'

export default function ShareLayout() {
  return (
    <>
      <div className="h-screen flex overflow-hidden bg-white">
        <div className="flex-1 min-w-0 h-full py-0 pr-0 relative">
          <div className="flex h-full bg-[var(--background-gray-main)]">
            <div className="flex flex-1 min-w-0 min-h-0">
              <Outlet />
              <FilePanel />
            </div>
          </div>
        </div>
      </div>
      <CustomDialog />
      <SessionFileList />
    </>
  )
}
