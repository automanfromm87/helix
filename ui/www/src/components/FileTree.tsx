import { useCallback, useEffect, useState } from 'react'
import {
  ChevronDown,
  ChevronRight,
  Folder,
  FolderOpen,
  RefreshCw,
} from 'lucide-react'

import { listDir, type FileListEntry } from '@/api/agent'
import { cn } from '@/lib/utils'


interface Props {
  sessionId: string
  /** Absolute path the tree is rooted at. */
  rootPath: string
  /** Optional path that is currently selected (highlighted + auto-expanded). */
  selectedPath?: string
  /** Fired when the user clicks any file (not directory). */
  onSelectFile?: (entry: FileListEntry) => void
  className?: string
}


/**
 * Lazy file-tree explorer.
 *
 * - The root and any expanded directory are fetched on demand via
 *   `/sessions/:id/file/list`. Children below an unexpanded folder are
 *   never fetched — keeps API + render cost proportional to what the
 *   user has actually opened.
 * - When `selectedPath` changes (e.g. the agent's `file_read` flips to
 *   a different file), the tree auto-expands every ancestor so the
 *   selection is visible without manual clicking.
 * - Failed fetches surface inline next to the directory row, not as a
 *   modal — sandbox flakes shouldn't blow away the whole tree.
 */
export default function FileTree({
  sessionId,
  rootPath,
  selectedPath,
  onSelectFile,
  className,
}: Props) {
  // Per-directory cached children, keyed by absolute path. `undefined`
  // means "not loaded yet" so we know to fetch lazily; an empty array
  // is a valid "loaded, no children".
  const [children, setChildren] = useState<Record<string, FileListEntry[] | undefined>>({})
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [loading, setLoading] = useState<Set<string>>(new Set())
  const [errors, setErrors] = useState<Record<string, string>>({})

  const loadDir = useCallback(async (path: string) => {
    setLoading((prev) => new Set(prev).add(path))
    setErrors((prev) => {
      const next = { ...prev }
      delete next[path]
      return next
    })
    try {
      const res = await listDir(sessionId, path)
      setChildren((prev) => ({ ...prev, [path]: res.entries }))
    } catch (e) {
      setErrors((prev) => ({ ...prev, [path]: (e as Error).message }))
    } finally {
      setLoading((prev) => {
        const next = new Set(prev)
        next.delete(path)
        return next
      })
    }
  }, [sessionId])

  // Initial root load + reload when sessionId / rootPath changes.
  useEffect(() => {
    setChildren({})
    setExpanded(new Set([rootPath]))
    setErrors({})
    void loadDir(rootPath)
  }, [sessionId, rootPath, loadDir])

  // Auto-expand ancestors of the selected path so the highlight is
  // visible. Walks up the chain stopping at rootPath; only fires fetches
  // for ancestors that aren't already cached.
  useEffect(() => {
    if (!selectedPath || !selectedPath.startsWith(rootPath)) return
    const ancestors: string[] = []
    let cur = selectedPath
    while (cur && cur !== rootPath && cur !== '/') {
      const slash = cur.lastIndexOf('/')
      if (slash <= 0) break
      cur = cur.slice(0, slash)
      ancestors.push(cur)
      if (cur === rootPath) break
    }
    setExpanded((prev) => {
      const next = new Set(prev)
      for (const a of ancestors) next.add(a)
      return next
    })
    for (const a of ancestors) {
      if (children[a] === undefined && !loading.has(a)) {
        void loadDir(a)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPath, rootPath, sessionId])

  const toggle = useCallback(
    (entry: FileListEntry) => {
      setExpanded((prev) => {
        const next = new Set(prev)
        if (next.has(entry.path)) {
          next.delete(entry.path)
        } else {
          next.add(entry.path)
          // Lazy fetch on first expand.
          if (children[entry.path] === undefined && !loading.has(entry.path)) {
            void loadDir(entry.path)
          }
        }
        return next
      })
    },
    [children, loading, loadDir],
  )

  const refresh = useCallback(() => {
    setChildren({})
    setErrors({})
    setExpanded(new Set([rootPath]))
    void loadDir(rootPath)
  }, [rootPath, loadDir])

  return (
    <div className={cn('flex flex-col h-full bg-[var(--background-gray-main)]', className)}>
      <div className="h-[36px] flex items-center justify-between px-2 border-b border-[var(--border-main)] flex-shrink-0">
        <div
          className="flex items-center gap-1.5 text-[12px] font-medium text-[var(--text-tertiary)] uppercase tracking-wide truncate"
          title={rootPath}
        >
          <Folder size={14} className="flex-shrink-0" />
          <span className="truncate">{rootPath.split('/').filter(Boolean).pop() ?? 'Explorer'}</span>
        </div>
        <button
          type="button"
          onClick={refresh}
          title="Refresh"
          className="h-6 w-6 inline-flex items-center justify-center rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-tertiary)] flex-shrink-0"
        >
          <RefreshCw size={12} />
        </button>
      </div>
      <div className="flex-1 min-h-0 overflow-auto py-1 text-[13px] font-mono">
        <TreeLevel
          entries={children[rootPath] ?? []}
          expanded={expanded}
          loading={loading}
          errors={errors}
          children_={children}
          selectedPath={selectedPath}
          onToggle={toggle}
          onSelectFile={onSelectFile}
          depth={0}
        />
        {loading.has(rootPath) && (children[rootPath] ?? []).length === 0 && (
          <div className="px-3 py-2 text-[11px] text-[var(--text-tertiary)]">Loading…</div>
        )}
        {errors[rootPath] && (
          <div className="px-3 py-3 text-[11px] text-[var(--function-error)] break-words">
            {errors[rootPath]}
          </div>
        )}
        {!loading.has(rootPath) && !errors[rootPath] && (children[rootPath] ?? []).length === 0 && (
          <div className="px-3 py-3 text-[11px] text-[var(--text-tertiary)] italic">
            (empty directory)
          </div>
        )}
      </div>
    </div>
  )
}


// --- recursive renderer --------------------------------------------------
//
// Pulled out as a separate component so each level can be flat-mapped over
// `children[entry.path]` without bloating the parent. Keys use full path so
// reorderings within a directory don't reset row state.

interface TreeLevelProps {
  entries: FileListEntry[]
  expanded: Set<string>
  loading: Set<string>
  errors: Record<string, string>
  children_: Record<string, FileListEntry[] | undefined>
  selectedPath?: string
  onToggle: (entry: FileListEntry) => void
  onSelectFile?: (entry: FileListEntry) => void
  depth: number
}

function TreeLevel({
  entries,
  expanded,
  loading,
  errors,
  children_,
  selectedPath,
  onToggle,
  onSelectFile,
  depth,
}: TreeLevelProps) {
  return (
    <>
      {entries.map((e) => (
        <TreeRow
          key={e.path}
          entry={e}
          expanded={expanded}
          loading={loading}
          errors={errors}
          children_={children_}
          selectedPath={selectedPath}
          onToggle={onToggle}
          onSelectFile={onSelectFile}
          depth={depth}
        />
      ))}
    </>
  )
}


type TreeRowProps = Omit<TreeLevelProps, 'entries'> & { entry: FileListEntry }

function TreeRow({
  entry,
  expanded,
  loading,
  errors,
  children_,
  selectedPath,
  onToggle,
  onSelectFile,
  depth,
}: TreeRowProps) {
  const isOpen = expanded.has(entry.path)
  const isLoading = loading.has(entry.path)
  const childEntries = children_[entry.path]
  const isSelected = entry.path === selectedPath

  const handleClick = () => {
    if (entry.is_dir) onToggle(entry)
    else onSelectFile?.(entry)
  }

  const indent = 8 + depth * 12
  return (
    <>
      <button
        type="button"
        onClick={handleClick}
        title={entry.path}
        className={cn(
          'w-full flex items-center gap-1 px-2 py-[2px] text-left',
          'hover:bg-[var(--fill-tsp-white-light)]',
          isSelected && !entry.is_dir && 'bg-[var(--fill-tsp-white-main)] text-[var(--text-brand)]',
        )}
        style={{ paddingLeft: indent }}
      >
        {entry.is_dir ? (
          <>
            {isOpen ? (
              <ChevronDown size={12} className="flex-shrink-0 text-[var(--icon-tertiary)]" />
            ) : (
              <ChevronRight size={12} className="flex-shrink-0 text-[var(--icon-tertiary)]" />
            )}
            {isOpen ? (
              <FolderOpen size={14} className="flex-shrink-0 text-[var(--icon-secondary)]" />
            ) : (
              <Folder size={14} className="flex-shrink-0 text-[var(--icon-secondary)]" />
            )}
          </>
        ) : (
          <>
            {/* spacer so files line up with directories that have a chevron */}
            <span className="w-3 flex-shrink-0" aria-hidden />
            <FileLeafIcon name={entry.name} />
          </>
        )}
        <span className="truncate text-[var(--text-primary)]">{entry.name}</span>
      </button>
      {entry.is_dir && isOpen && (
        <>
          {isLoading && childEntries === undefined && (
            <div
              className="text-[11px] text-[var(--text-tertiary)] py-[2px]"
              style={{ paddingLeft: indent + 22 }}
            >
              Loading…
            </div>
          )}
          {errors[entry.path] && (
            <div
              className="text-[11px] text-[var(--function-error)] py-[2px] truncate"
              style={{ paddingLeft: indent + 22 }}
              title={errors[entry.path]}
            >
              {errors[entry.path]}
            </div>
          )}
          {childEntries && (
            <TreeLevel
              entries={childEntries}
              expanded={expanded}
              loading={loading}
              errors={errors}
              children_={children_}
              selectedPath={selectedPath}
              onToggle={onToggle}
              onSelectFile={onSelectFile}
              depth={depth + 1}
            />
          )}
        </>
      )}
    </>
  )
}


// --- leaf icon -----------------------------------------------------------
//
// Tiny dot + ext color hint. Not perfect language detection — VS Code-class
// theming would need a full icon pack, which is out of scope. The header
// in FileToolView already shows a proper file icon for the selected file.

function FileLeafIcon({ name }: { name: string }) {
  const ext = name.split('.').pop()?.toLowerCase() ?? ''
  const color = colorForExt(ext)
  return (
    <span
      aria-hidden
      className="w-2 h-2 rounded-[1px] flex-shrink-0"
      style={{ background: color }}
    />
  )
}

function colorForExt(ext: string): string {
  switch (ext) {
    case 'ts':
    case 'tsx':
      return '#3178c6'
    case 'js':
    case 'jsx':
    case 'mjs':
    case 'cjs':
      return '#f7df1e'
    case 'py':
      return '#3776ab'
    case 'json':
    case 'jsonc':
      return '#cbcb41'
    case 'md':
    case 'markdown':
      return '#519aba'
    case 'html':
      return '#e44d26'
    case 'css':
    case 'scss':
    case 'sass':
      return '#1572b6'
    case 'go':
      return '#00add8'
    case 'rs':
      return '#dea584'
    case 'sh':
    case 'bash':
      return '#89e051'
    case 'yml':
    case 'yaml':
      return '#cb171e'
    case 'lock':
      return '#888'
    default:
      return '#888'
  }
}
