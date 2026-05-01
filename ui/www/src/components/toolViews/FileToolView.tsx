import { useEffect, useMemo, useState } from 'react'
import {
  Check,
  Copy,
  FileCode,
  FileJson,
  FileText,
  FileType,
  PanelLeft,
  type LucideIcon,
} from 'lucide-react'

import FileTree from '@/components/FileTree'
import MonacoEditor from '@/components/ui/MonacoEditor'
import { viewFile, type FileListEntry } from '@/api/agent'
import type { ToolViewProps } from '@/constants/tool'
import { copyToClipboard } from '@/utils/dom'
import { cn } from '@/lib/utils'

// Sandbox-side home directory — the floor of where the user's project
// can live. We derive a more specific root (e.g. /home/ubuntu/project)
// from the file the agent is currently touching when possible, but
// fall back here if no file path is available.
const HOME_ROOT = '/home/ubuntu'

/**
 * Pick a tree root for the explorer.
 *
 * Heuristic: take the first three slash-separated segments of the file
 * path the agent is currently touching. For `/home/ubuntu/project/...`
 * that's `/home/ubuntu/project` — i.e. the project directory, which is
 * what the user almost always wants to see in the explorer (not the
 * dotfile-only home dir above it). Falls back to HOME_ROOT when no
 * file path is available or it doesn't sit under /home/<user>/<project>.
 */
function deriveTreeRoot(filePath: string): string {
  if (!filePath || !filePath.startsWith('/home/')) return HOME_ROOT
  const parts = filePath.split('/').filter(Boolean)
  if (parts.length >= 3) return '/' + parts.slice(0, 3).join('/')
  return HOME_ROOT
}


/**
 * File viewer panel.
 *
 * Shows the contents of whatever file the agent's `file_read` /
 * `file_write` last touched, in a Monaco editor with sane code-editor
 * defaults — line numbers, monospace font, no word-wrap (so source
 * lines stay on one row instead of looking like prose), bracket-pair
 * colorization, and a sticky path/copy header.
 *
 * Live mode (live=true): re-fetches the file every 5s while the panel
 * is the foreground tab, so edits made by `file_write` appear without
 * a manual refresh. Off-tab polling is suppressed.
 */
export default function FileToolView({ sessionId, toolContent, live }: ToolViewProps) {
  const [fileContent, setFileContent] = useState('')
  const [copied, setCopied] = useState(false)
  const [showTree, setShowTree] = useState(true)
  // Currently-selected file in the editor pane. Starts as whatever the
  // tool wrote/read last; clicking a file in the tree replaces it.
  const [selectedPath, setSelectedPath] = useState<string>('')

  const toolFilePath = useMemo<string>(
    () => (toolContent?.args?.file ? String(toolContent.args.file) : ''),
    [toolContent?.args?.file],
  )

  // The active file path: user's tree selection if they've made one,
  // otherwise the tool's file. Reset back to tool path when the tool
  // changes (new tool_call_id) so the panel follows the agent.
  const filePath = selectedPath || toolFilePath

  // Tree root follows whichever file is currently active — when the
  // agent jumps from /home/ubuntu/projA/... to /home/ubuntu/projB/...
  // the explorer reroots automatically.
  const treeRoot = useMemo(() => deriveTreeRoot(filePath), [filePath])
  const fileName = useMemo(() => filePath.split('/').pop() ?? '', [filePath])
  const fileDir = useMemo(() => {
    const idx = filePath.lastIndexOf('/')
    return idx >= 0 ? filePath.slice(0, idx) : ''
  }, [filePath])
  const ext = useMemo(() => fileName.split('.').pop()?.toLowerCase() ?? '', [fileName])
  const language = useMemo(() => extensionToLanguage(ext), [ext])
  const FileIcon = useMemo(() => iconForExt(ext), [ext])

  const lineCount = useMemo(
    () => (fileContent ? fileContent.split('\n').length : 0),
    [fileContent],
  )

  // Reset the user's tree selection whenever the underlying tool
  // changes — otherwise jumping between two consecutive file_read tools
  // would leave the panel stuck on the previously-selected tree entry.
  useEffect(() => {
    setSelectedPath('')
  }, [toolContent.tool_call_id])

  const loadFileContent = async () => {
    // Tree selection always uses live fetch (the cached toolContent only
    // has the agent's last file, not whatever the user clicked).
    if (selectedPath) {
      try {
        const response = await viewFile(sessionId, selectedPath)
        setFileContent(response.content)
      } catch (e) {
        console.error('Failed to load file content:', e)
        setFileContent('')
      }
      return
    }
    if (!live) {
      setFileContent(toolContent.content?.content ?? '')
      return
    }
    if (!toolFilePath) return
    try {
      const response = await viewFile(sessionId, toolFilePath)
      setFileContent(response.content)
    } catch (e) {
      console.error('Failed to load file content:', e)
    }
  }

  useEffect(() => {
    void loadFileContent()
    // Polling only re-fetches the agent's current tool target when it's
    // still in flight. User-selected files don't auto-refresh — the user
    // can click again to reload.
    if (selectedPath) return
    if (!live || !toolFilePath) return
    // Skip polling while the tab is hidden — Chrome's "slow tab" detector
    // flags background tabs that keep doing network/work, and there's no
    // user-visible benefit to refreshing content nobody can see.
    const id = window.setInterval(() => {
      if (document.visibilityState !== 'visible') return
      void loadFileContent()
    }, 5000)
    return () => window.clearInterval(id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [live, selectedPath, toolFilePath, toolContent.timestamp])

  const handleSelectFile = (entry: FileListEntry) => {
    setSelectedPath(entry.path)
  }

  const handleCopy = async () => {
    if (!fileContent) return
    const ok = await copyToClipboard(fileContent)
    if (ok) {
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    }
  }

  return (
    <div className="flex flex-col h-full w-full">
      {/* Header: tree toggle + file icon + filename + breadcrumb + lang pill + copy */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[var(--border-main)] bg-[var(--background-gray-main)] rounded-t-[12px]">
        <button
          type="button"
          onClick={() => setShowTree((v) => !v)}
          title={showTree ? 'Hide explorer' : 'Show explorer'}
          className={cn(
            'h-7 w-7 inline-flex items-center justify-center rounded-md flex-shrink-0',
            'hover:bg-[var(--fill-tsp-white-light)]',
            showTree
              ? 'text-[var(--text-primary)]'
              : 'text-[var(--icon-tertiary)]',
          )}
        >
          <PanelLeft size={14} />
        </button>
        <FileIcon
          size={18}
          className="text-[var(--icon-secondary)] flex-shrink-0"
          aria-hidden
        />
        <div className="flex-1 min-w-0 flex flex-col">
          <div className="flex items-center gap-2">
            <span
              className="text-[13px] font-medium text-[var(--text-primary)] truncate"
              title={fileName}
            >
              {fileName || '(no file)'}
            </span>
            {language !== 'plaintext' && (
              <span className="text-[10px] uppercase tracking-wide font-mono px-1.5 py-[1px] rounded-[4px] bg-[var(--fill-tsp-white-main)] text-[var(--text-tertiary)] flex-shrink-0">
                {language}
              </span>
            )}
          </div>
          {fileDir && (
            <span
              className="text-[11px] text-[var(--text-tertiary)] truncate font-mono"
              title={fileDir}
            >
              {fileDir}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 flex-shrink-0">
          {lineCount > 0 && (
            <span className="text-[11px] text-[var(--text-tertiary)] tabular-nums">
              {lineCount} {lineCount === 1 ? 'line' : 'lines'}
            </span>
          )}
          <button
            type="button"
            onClick={handleCopy}
            disabled={!fileContent}
            title="Copy file contents"
            className={cn(
              'h-7 px-2 inline-flex items-center gap-1 rounded-md text-[12px]',
              'border border-[var(--border-btn-main)] bg-[var(--background-menu-white)]',
              'hover:bg-[var(--fill-tsp-white-light)]',
              'disabled:opacity-40 disabled:cursor-not-allowed',
              'transition-colors',
            )}
          >
            {copied ? (
              <>
                <Check size={12} className="text-[var(--function-success)]" />
                <span>Copied</span>
              </>
            ) : (
              <>
                <Copy size={12} />
                <span>Copy</span>
              </>
            )}
          </button>
        </div>
      </div>

      {/* Body: optional tree on the left + editor on the right */}
      <div className="flex flex-1 min-h-0 w-full">
        {showTree && (
          <FileTree
            sessionId={sessionId}
            rootPath={treeRoot}
            selectedPath={filePath}
            onSelectFile={handleSelectFile}
            className="w-[260px] flex-shrink-0 border-r border-[var(--border-main)]"
          />
        )}
        <div className="flex-1 min-h-0 min-w-0">
          {fileContent ? (
            <MonacoEditor
              value={fileContent}
              filename={fileName}
              readOnly
              theme="vs"
              lineNumbers="on"
              wordWrap="off"
              minimap
              scrollBeyondLastLine={false}
              automaticLayout
            />
          ) : (
            <EmptyState filePath={filePath} />
          )}
        </div>
      </div>
    </div>
  )
}


function EmptyState({ filePath }: { filePath: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 h-full text-[var(--text-tertiary)] px-6">
      <FileText size={28} className="opacity-50" />
      <div className="text-sm">No file content captured</div>
      {filePath && (
        <div className="text-xs font-mono break-all text-center max-w-md">
          {filePath}
        </div>
      )}
    </div>
  )
}


// --- icon picker ---------------------------------------------------------
//
// Chooses a lucide icon matching the file's role at a glance. Kept
// deliberately small — defaulting to FileText for anything unknown is
// fine; the language pill in the header carries more precise info.

function iconForExt(ext: string): LucideIcon {
  switch (ext) {
    case 'json':
    case 'jsonc':
      return FileJson
    case 'ts':
    case 'tsx':
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
    case 'py':
    case 'go':
    case 'rs':
    case 'java':
    case 'rb':
    case 'php':
    case 'c':
    case 'cpp':
    case 'h':
    case 'hpp':
    case 'cs':
    case 'kt':
    case 'swift':
    case 'sh':
    case 'bash':
    case 'zsh':
      return FileCode
    case 'md':
    case 'markdown':
    case 'txt':
    case 'log':
      return FileText
    case 'html':
    case 'css':
    case 'scss':
    case 'sass':
    case 'less':
      return FileType
    default:
      return FileText
  }
}


// --- language detection (mirrors MonacoEditor.tsx so we can show a pill) -

function extensionToLanguage(ext: string): string {
  const map: Record<string, string> = {
    ts: 'typescript',
    tsx: 'typescript',
    js: 'javascript',
    jsx: 'javascript',
    mjs: 'javascript',
    cjs: 'javascript',
    py: 'python',
    java: 'java',
    go: 'go',
    rs: 'rust',
    php: 'php',
    rb: 'ruby',
    c: 'c',
    cpp: 'cpp',
    h: 'c',
    hpp: 'cpp',
    md: 'markdown',
    markdown: 'markdown',
    json: 'json',
    jsonc: 'json',
    yaml: 'yaml',
    yml: 'yaml',
    sh: 'shell',
    bash: 'shell',
    zsh: 'shell',
    html: 'html',
    css: 'css',
    scss: 'scss',
    sass: 'sass',
    less: 'less',
    sql: 'sql',
    toml: 'ini',
    ini: 'ini',
    xml: 'xml',
    dockerfile: 'dockerfile',
  }
  return map[ext] ?? 'plaintext'
}
