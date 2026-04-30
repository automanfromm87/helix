import { useEffect, useState } from 'react'

import { getFileDownloadUrl } from '@/api/file'
import type { FilePreviewProps } from './types'

export default function ImageFilePreview({ file }: FilePreviewProps) {
  const [url, setUrl] = useState('')
  useEffect(() => {
    void getFileDownloadUrl(file).then(setUrl).catch(console.error)
  }, [file])
  if (!url) return null
  return (
    <div className="h-full w-full flex items-center justify-center bg-[var(--background-gray-main)] p-4">
      <img src={url} alt={file.filename} className="max-h-full max-w-full" />
    </div>
  )
}
