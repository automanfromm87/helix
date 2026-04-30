import { useEffect, useState } from 'react'

import MonacoEditor from '@/components/ui/MonacoEditor'
import { getFileDownloadUrl } from '@/api/file'
import type { FilePreviewProps } from './types'

export default function CodeFilePreview({ file }: FilePreviewProps) {
  const [content, setContent] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const url = await getFileDownloadUrl(file)
        const res = await fetch(url)
        const text = await res.text()
        if (!cancelled) setContent(text)
      } catch (e) {
        console.error('Failed to load file:', e)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [file])

  return (
    <div className="h-full">
      <MonacoEditor
        value={content}
        filename={file.filename}
        readOnly
        theme="vs"
        lineNumbers="on"
        wordWrap="on"
        automaticLayout
      />
    </div>
  )
}
