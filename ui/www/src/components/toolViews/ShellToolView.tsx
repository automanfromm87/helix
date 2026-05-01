import { useEffect, useMemo, useState } from 'react'

import { viewShellSession } from '@/api/agent'
import type { ConsoleRecord } from '@/types/response'
import type { ToolViewProps } from '@/constants/tool'

export default function ShellToolView({ sessionId, toolContent, live }: ToolViewProps) {
  const [shell, setShell] = useState('')

  const shellSessionId = useMemo<string>(
    () => (toolContent?.args?.id ? String(toolContent.args.id) : ''),
    [toolContent?.args?.id],
  )

  const updateShellContent = (records: ConsoleRecord[] | undefined) => {
    if (!records) return
    let html = ''
    for (const e of records) {
      html += `<span style="color: rgb(0, 187, 0);">${e.ps1}</span><span> ${e.command}</span>\n`
      html += `<span>${e.output}</span>\n`
    }
    setShell((prev) => (prev !== html ? html : prev))
  }

  const loadShellContent = async () => {
    if (!live) {
      updateShellContent(toolContent.content?.console)
      return
    }
    if (!shellSessionId) return
    try {
      const response = await viewShellSession(sessionId, shellSessionId)
      updateShellContent(response.console)
    } catch (e) {
      console.error('Failed to load shell content:', e)
    }
  }

  // Load + 5s autorefresh while live. Polling pauses when the tab is in
  // the background so Chrome's "slow tab" battery detector doesn't flag us.
  useEffect(() => {
    void loadShellContent()
    if (!live || !shellSessionId) return
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return
      void loadShellContent()
    }, 5000)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, shellSessionId, toolContent.timestamp])

  return (
    <>
      <div className="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
            {shellSessionId}
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-y-auto">
        <div className="flex flex-col flex-1 min-h-0">
          {shell ? (
            <div
              className="py-2 flex-1 font-mono text-sm leading-relaxed px-3 outline-none overflow-auto whitespace-pre-wrap break-all"
            >
              <code dangerouslySetInnerHTML={{ __html: shell }} />
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 py-10 text-[var(--text-tertiary)]">
              <div className="text-sm">No shell output captured</div>
              {toolContent?.args?.command && (
                <div className="text-xs font-mono">$ {String(toolContent.args.command)}</div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
