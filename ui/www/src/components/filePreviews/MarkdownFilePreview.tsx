import { useEffect, useState } from 'react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'

import { getFileDownloadUrl } from '@/api/file'
import type { FilePreviewProps } from './types'

export default function MarkdownFilePreview({ file }: FilePreviewProps) {
  const [html, setHtml] = useState('')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const url = await getFileDownloadUrl(file)
        const res = await fetch(url)
        const text = await res.text()
        if (cancelled) return
        const rendered = marked(text) as string
        setHtml(DOMPurify.sanitize(rendered, { ADD_ATTR: ['target'] }))
      } catch (e) {
        console.error('Failed to load markdown:', e)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [file])

  return (
    <div
      className="h-full overflow-auto p-6 prose prose-sm max-w-none dark:prose-invert"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
