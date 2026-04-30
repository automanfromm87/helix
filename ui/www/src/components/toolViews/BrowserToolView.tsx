import { useMemo } from 'react'

import VNCViewer from '@/components/VNCViewer'
import { TakeOverIcon } from '@/components/icons'
import type { ToolViewProps } from '@/constants/tool'

export default function BrowserToolView({
  sessionId,
  toolContent,
  live,
  isShare,
}: ToolViewProps) {
  const screenshot = toolContent.content?.screenshot
  const imageUrl = useMemo(() => screenshot ?? '', [screenshot])

  const takeOver = () => {
    window.dispatchEvent(
      new CustomEvent('takeover', { detail: { sessionId, active: true } }),
    )
  }

  return (
    <>
      <div className="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
            {toolContent?.args?.url || 'Browser'}
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-hidden">
        <div className="relative h-full w-full bg-[var(--fill-white)] flex items-center justify-center">
          {live ? (
            <div className="w-full h-full">
              <VNCViewer sessionId={sessionId} enabled={live} viewOnly={true} />
            </div>
          ) : imageUrl ? (
            // object-contain + max bounds keeps the screenshot's aspect ratio
            // and centers it inside the panel instead of letting `w-full`
            // stretch it to the panel width regardless of image dimensions.
            <img
              alt="Image Preview"
              className="cursor-pointer max-w-full max-h-full object-contain block"
              referrerPolicy="no-referrer"
              src={imageUrl}
            />
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 text-[var(--text-tertiary)] px-6 text-center">
              <div className="text-sm">No snapshot captured for this step</div>
              {toolContent?.args?.url && (
                <div className="text-xs font-mono break-all">
                  {String(toolContent.args.url)}
                </div>
              )}
            </div>
          )}
          {!isShare && (
              <button
                type="button"
                onClick={takeOver}
                className="absolute right-[10px] bottom-[10px] z-20 min-w-10 h-10 flex items-center justify-center rounded-full bg-[var(--background-white-main)] text-[var(--text-primary)] border border-[var(--border-main)] shadow-[0px_5px_16px_0px_var(--shadow-S),0px_0px_1.25px_0px_var(--shadow-S)] backdrop-blur-3xl cursor-pointer hover:bg-[var(--text-brand)] hover:px-4 hover:text-[var(--text-white)] group transition-[width] duration-300"
              >
                <TakeOverIcon />
                <span className="text-sm max-w-0 overflow-hidden whitespace-nowrap opacity-0 transition-all duration-300 group-hover:max-w-[200px] group-hover:opacity-100 group-hover:ml-1 group-hover:text-[var(--text-white)]">
                  Take Over
                </span>
              </button>
          )}
        </div>
      </div>
    </>
  )
}
