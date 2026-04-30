import { useEffect, useState } from 'react'
import { Download } from 'lucide-react'

import { getFileDownloadUrl } from '@/api/file'
import type { FilePreviewProps } from './types'

export default function UnknownFilePreview({ file }: FilePreviewProps) {
  const [url, setUrl] = useState('')

  useEffect(() => {
    void getFileDownloadUrl(file).then(setUrl).catch(console.error)
  }, [file])

  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 px-6 py-10 text-center">
      <p className="text-[var(--text-secondary)] text-sm">This format cannot be previewed</p>
      <p className="text-[var(--text-tertiary)] text-xs">
        Please download the file to view its content
      </p>
      {url && (
        <a
          href={url}
          download={file.filename}
          className="inline-flex items-center gap-2 px-3 h-9 rounded-md bg-[var(--Button-primary-black)] text-[var(--text-onblack)] text-sm hover:opacity-90"
        >
          <Download size={16} />
          Download
        </a>
      )}
    </div>
  )
}
