import type { ComponentType } from 'react'
import { FileText, Code as CodeIcon } from 'lucide-react'

import UnknownFilePreview from '@/components/filePreviews/UnknownFilePreview'
import MarkdownFilePreview from '@/components/filePreviews/MarkdownFilePreview'
import CodeFilePreview from '@/components/filePreviews/CodeFilePreview'
import ImageFilePreview from '@/components/filePreviews/ImageFilePreview'
import type { FilePreviewProps } from '@/components/filePreviews/types'

export interface FileType {
  Icon: ComponentType<any>
  Preview: ComponentType<FilePreviewProps>
}

const codeFileExtensions = [
  'py', 'js', 'ts', 'jsx', 'tsx', 'vue',
  'java', 'c', 'cpp', 'h', 'hpp',
  'go', 'rust', 'php', 'ruby', 'swift',
  'kotlin', 'scala', 'haskell', 'erlang', 'elixir',
  'ocaml', 'fsharp', 'dart', 'julia',
  'lua', 'perl', 'r', 'sh', 'bash',
  'css', 'scss', 'sass', 'less', 'txt',
  'html', 'xml', 'json', 'yaml', 'yml',
  'sql', 'dockerfile', 'toml', 'ini', 'conf',
]

const imageFileExtensions = [
  'jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg', 'ico', 'tiff', 'tif', 'heic', 'heif',
]

const documentFileExtensions = [
  'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'odt', 'ods', 'odp',
]

const videoFileExtensions = ['mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'mkv', '3gp', 'ogv']

const audioFileExtensions = ['mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'opus']

const archiveFileExtensions = ['zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'lzma']

export const getFileType = (filename: string): FileType => {
  const ext = filename.split('.').pop()?.toLowerCase()

  if (ext === 'md') {
    return { Icon: FileText, Preview: MarkdownFilePreview }
  }
  if (ext && codeFileExtensions.includes(ext)) {
    return { Icon: CodeIcon, Preview: CodeFilePreview }
  }
  if (ext && imageFileExtensions.includes(ext)) {
    return { Icon: FileText, Preview: ImageFilePreview }
  }
  return { Icon: FileText, Preview: UnknownFilePreview }
}

export const getFileTypeText = (filename: string): string => {
  const ext = filename.split('.').pop()?.toLowerCase()
  if (!ext) return 'File'
  if (ext === 'txt') return 'Text'
  if (ext === 'md') return 'Markdown'
  if (codeFileExtensions.includes(ext)) return 'Code'
  if (imageFileExtensions.includes(ext)) return 'Image'
  if (ext === 'pdf') return 'PDF'
  if (['doc', 'docx'].includes(ext)) return 'Word'
  if (['xls', 'xlsx'].includes(ext)) return 'Excel'
  if (['ppt', 'pptx'].includes(ext)) return 'PowerPoint'
  if (documentFileExtensions.includes(ext)) return 'Document'
  if (videoFileExtensions.includes(ext)) return 'Video'
  if (audioFileExtensions.includes(ext)) return 'Audio'
  if (archiveFileExtensions.includes(ext)) return 'Archive'
  return 'File'
}

export function formatFileSize(
  bytes: number | null | undefined,
  decimals: number = 1,
): string {
  if (!bytes || bytes === 0) return '0 B'
  const k = 1024
  const dm = decimals < 0 ? 0 : decimals
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB']
  const i = Math.floor(Math.log(bytes) / Math.log(k))
  return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i]
}
