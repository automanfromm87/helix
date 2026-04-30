import { useEffect, useMemo, useState } from 'react'

import MonacoEditor from '@/components/ui/MonacoEditor'
import { viewFile } from '@/api/agent'
import type { ToolViewProps } from '@/constants/tool'

export default function FileToolView({ sessionId, toolContent, live }: ToolViewProps) {
  const [fileContent, setFileContent] = useState('')

  const filePath = useMemo<string>(
    () => (toolContent?.args?.file ? String(toolContent.args.file) : ''),
    [toolContent?.args?.file],
  )
  const fileName = useMemo(() => filePath.split('/').pop() ?? '', [filePath])

  const loadFileContent = async () => {
    if (!live) {
      setFileContent(toolContent.content?.content ?? '')
      return
    }
    if (!filePath) return
    try {
      const response = await viewFile(sessionId, filePath)
      setFileContent(response.content)
    } catch (e) {
      console.error('Failed to load file content:', e)
    }
  }

  useEffect(() => {
    void loadFileContent()
    if (!live || !filePath) return
    const id = window.setInterval(() => void loadFileContent(), 5000)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, filePath, toolContent.timestamp])

  return (
    <>
      <div className="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
            {fileName}
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-y-auto">
        <div className="flex flex-col min-h-0 h-full relative">
          {fileContent ? (
            <section style={{ display: 'flex', position: 'relative', width: '100%', height: '100%' }}>
              <MonacoEditor
                value={fileContent}
                filename={fileName}
                readOnly
                theme="vs"
                lineNumbers="off"
                wordWrap="on"
                minimap={false}
                scrollBeyondLastLine={false}
                automaticLayout
              />
            </section>
          ) : (
            <div className="flex flex-col items-center justify-center gap-2 py-10 text-[var(--text-tertiary)]">
              <div className="text-sm">No file content captured</div>
              {filePath && <div className="text-xs font-mono break-all">{filePath}</div>}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
