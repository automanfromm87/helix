import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  AlertCircle,
  Ban,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Circle,
  Columns3,
  GitBranch,
  GitCommit,
  History,
  Loader2,
  RotateCcw,
  X,
} from 'lucide-react'

import Markdown from './Markdown'
import { forkPlan, forkPlanMany, getPlanDiff, restorePlan } from '@/api/agent'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from './ui/Dialog'
import type { PlanEventData, TaskEventData, TaskStatusValue } from '@/types/event'
import { cn } from '@/lib/utils'
import { showErrorToast, showSuccessToast } from '@/utils/toast'

interface Props {
  plan: PlanEventData
  /**
   * Total plans on this session (for the "Plan N / M" indicator). When
   * undefined or 1, the navigation row is hidden — single-plan sessions
   * don't need it.
   */
  historyTotal?: number
  /**
   * Index into the history list the user is currently viewing.
   * 0 = newest (= live plan), historyTotal-1 = oldest. When > 0, the
   * panel shows a "viewing older plan" hint so the user knows the
   * displayed plan isn't the live one.
   */
  historyIndex?: number
  /**
   * Callback fired when the user clicks ‹ or ›. `delta` is +1 (older)
   * or -1 (newer). Parent clamps to bounds.
   */
  onHistoryNav?: (delta: 1 | -1) => void
}

const STATUS_LABEL: Record<string, string> = {
  planning: 'Planning',
  executing: 'In progress',
  completed: 'Completed',
  failed: 'Failed',
}


/**
 * Status icon for a task row.
 *
 * Sizes are tuned for inline reading — 12px keeps the icon column narrow
 * so titles don't wrap unnecessarily, and the colored states are saturated
 * enough to read at-a-glance from a few feet away.
 */
function TaskIcon({ status }: { status: TaskStatusValue }) {
  switch (status) {
    case 'running':
      return (
        <Loader2
          size={14}
          className="text-[var(--text-brand)] animate-spin flex-shrink-0"
        />
      )
    case 'completed':
      return (
        <div className="size-[14px] rounded-full bg-[var(--function-success)] flex items-center justify-center flex-shrink-0">
          <Check size={9} className="text-white" strokeWidth={3} />
        </div>
      )
    case 'failed':
      return (
        <div className="size-[14px] rounded-full bg-[var(--function-error)] flex items-center justify-center flex-shrink-0">
          <AlertCircle size={9} className="text-white" />
        </div>
      )
    case 'blocked':
      return <Ban size={12} className="text-[var(--text-tertiary)] flex-shrink-0 opacity-60" />
    case 'pending':
    default:
      return (
        <Circle
          size={12}
          className="text-[var(--text-tertiary)] flex-shrink-0 opacity-50"
        />
      )
  }
}


/**
 * Detect a task whose title is actually the "Details: …" rider for the
 * preceding header task. The planner sometimes emits these as their own
 * plan rows, which renders as huge wall-of-text bullets if we treat them
 * like normal tasks. Visually nesting them under the previous task is
 * cheaper than retraining the planner.
 */
function isDetailRow(title: string): boolean {
  return /^details\s*:/i.test(title.trim())
}


/**
 * Strip the leading "Details:" tag — it's redundant once we render the
 * row indented under its parent.
 */
function detailBody(title: string): string {
  return title.replace(/^\s*details\s*:\s*/i, '').trim()
}


function HeaderRow({ task }: { task: TaskEventData }) {
  const dim = task.status === 'pending' || task.status === 'blocked'
  const isCompleted = task.status === 'completed'
  const [expanded, setExpanded] = useState(false)
  const hasDetails = Boolean(task.details && task.details.trim())

  return (
    <div
      className={cn(
        'group flex items-start gap-2 py-1.5 px-3 rounded-md transition-colors',
        task.status === 'running' && 'bg-[var(--fill-tsp-white-light)]',
      )}
      title={task.error || task.title}
    >
      <div className="pt-[3px]">
        <TaskIcon status={task.status} />
      </div>
      <div className="flex-1 min-w-0">
        <div
          className={cn(
            'flex items-center gap-1 text-[13px] leading-snug',
            dim && 'text-[var(--text-tertiary)]',
            !dim && 'text-[var(--text-primary)]',
            // Completed tasks: dim + reduced opacity rather than
            // strikethrough — line-through is hard to read in CJK fonts and
            // turns long plans into a "wall of struck-out text".
            isCompleted && 'text-[var(--text-tertiary)] opacity-60',
          )}
        >
          {hasDetails && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation()
                setExpanded((v) => !v)
              }}
              className="flex-shrink-0 -ml-[18px] mr-[6px] text-[var(--icon-tertiary)] opacity-0 group-hover:opacity-100 transition-opacity"
              aria-label={expanded ? 'Collapse details' : 'Expand details'}
            >
              {expanded ? <ChevronDown size={11} /> : <ChevronUp size={11} className="rotate-180" />}
            </button>
          )}
          <span className="font-medium line-clamp-2 break-words">{task.title}</span>
        </div>
        {hasDetails && expanded && (
          <div className="mt-1.5 mb-0.5 text-[12px] text-[var(--text-secondary)] markdown-content">
            <Markdown content={task.details ?? ''} />
          </div>
        )}
        {task.error && (
          <div className="text-[11px] mt-0.5 text-[var(--function-error)] truncate">
            {task.error}
          </div>
        )}
      </div>
      {task.retries > 0 && (
        <div
          className="text-[10px] text-[var(--text-tertiary)] flex-shrink-0 pt-1"
          title={`${task.retries} retry/retries`}
        >
          ↻{task.retries}
        </div>
      )}
    </div>
  )
}


function DetailRow({ task, last }: { task: TaskEventData; last: boolean }) {
  const isCompleted = task.status === 'completed'
  const dim = task.status === 'pending' || task.status === 'blocked'
  const body = detailBody(task.title)
  const [expanded, setExpanded] = useState(false)
  const isLong = body.length > 120

  return (
    <div className="flex items-start gap-2 px-3 -mt-0.5">
      {/* Vertical connector that nests this row under the prior header */}
      <div className="relative w-[14px] flex-shrink-0 self-stretch">
        <div
          className={cn(
            'absolute left-[6px] top-0 w-px bg-[var(--border-main)]',
            last ? 'h-[14px]' : 'inset-y-0',
          )}
        />
        <div className="absolute left-[6px] top-[14px] w-[8px] h-px bg-[var(--border-main)]" />
      </div>
      <div className="flex-1 min-w-0 py-1">
        <button
          type="button"
          onClick={() => isLong && setExpanded((v) => !v)}
          className={cn(
            'block w-full text-left text-[12px] leading-snug',
            dim && 'text-[var(--text-tertiary)] opacity-70',
            !dim && 'text-[var(--text-secondary)]',
            isCompleted && 'text-[var(--text-tertiary)]',
            isLong && !expanded && 'line-clamp-2 break-words',
            isLong && 'cursor-pointer',
          )}
          title={body}
        >
          {body}
        </button>
      </div>
      {task.retries > 0 && (
        <div
          className="text-[10px] text-[var(--text-tertiary)] flex-shrink-0 pt-1"
          title={`${task.retries} retry/retries`}
        >
          ↻{task.retries}
        </div>
      )}
    </div>
  )
}


export default function PlanPanel({
  plan,
  historyTotal,
  historyIndex,
  onHistoryNav,
}: Props) {
  const [collapsed, setCollapsed] = useState(false)

  const stats = useMemo(() => {
    const completed = plan.tasks.filter((t) => t.status === 'completed').length
    const total = plan.tasks.length
    return { completed, total }
  }, [plan.tasks])

  const isFailed = plan.status === 'failed'
  const isDone = plan.status === 'completed'
  const isActive = plan.status === 'planning' || plan.status === 'executing'

  // Navigation visible only when there's actual history. `historyIndex`
  // counts from 0 = newest, so "older" = +1 and "newer" = -1.
  const showNav =
    typeof historyTotal === 'number' &&
    historyTotal > 1 &&
    typeof historyIndex === 'number' &&
    typeof onHistoryNav === 'function'
  const isViewingHistory = showNav && (historyIndex ?? 0) > 0
  const canGoOlder = showNav && (historyIndex ?? 0) < (historyTotal ?? 1) - 1
  const canGoNewer = showNav && (historyIndex ?? 0) > 0

  return (
    <div className="border border-[var(--border-light)] bg-[var(--background-menu-white)] rounded-[12px] shadow-[0px_1px_2px_0px_rgba(0,0,0,0.04)]">
      {showNav && (
        <div
          className={cn(
            'flex items-center justify-between gap-2 px-4 py-1.5 text-[11px] border-b border-[var(--border-light)]',
            isViewingHistory
              ? 'bg-[var(--fill-tsp-yellow-light,_rgba(255,196,0,0.08))] text-[var(--text-secondary)]'
              : 'text-[var(--text-tertiary)]',
          )}
        >
          <div className="flex items-center gap-1.5">
            <History size={12} />
            {isViewingHistory ? (
              <span>
                Viewing previous plan{' '}
                <span className="font-semibold tabular-nums">
                  {(historyIndex ?? 0) + 1} / {historyTotal}
                </span>
              </span>
            ) : (
              <span>
                Latest plan{' '}
                <span className="font-semibold tabular-nums">
                  1 / {historyTotal}
                </span>
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={!canGoOlder}
              onClick={() => onHistoryNav?.(1)}
              title="Older plan"
              className={cn(
                'h-6 w-6 inline-flex items-center justify-center rounded-md transition-colors',
                canGoOlder
                  ? 'hover:bg-[var(--fill-tsp-white-light)] text-[var(--text-secondary)]'
                  : 'text-[var(--text-tertiary)] opacity-40 cursor-not-allowed',
              )}
            >
              <ChevronLeft size={14} />
            </button>
            <button
              type="button"
              disabled={!canGoNewer}
              onClick={() => onHistoryNav?.(-1)}
              title="Newer plan"
              className={cn(
                'h-6 w-6 inline-flex items-center justify-center rounded-md transition-colors',
                canGoNewer
                  ? 'hover:bg-[var(--fill-tsp-white-light)] text-[var(--text-secondary)]'
                  : 'text-[var(--text-tertiary)] opacity-40 cursor-not-allowed',
              )}
            >
              <ChevronRight size={14} />
            </button>
          </div>
        </div>
      )}
      <button
        onClick={() => setCollapsed((v) => !v)}
        className="w-full flex items-center gap-2 px-4 py-2.5 text-left"
      >
        <div className="flex-shrink-0">
          {isActive ? (
            <Loader2 size={16} className="text-[var(--text-brand)] animate-spin" />
          ) : isFailed ? (
            <AlertCircle size={16} className="text-[var(--function-error)]" />
          ) : isDone ? (
            <div className="size-4 rounded-full bg-[var(--function-success)] flex items-center justify-center">
              <Check size={10} className="text-white" strokeWidth={3} />
            </div>
          ) : (
            <Circle size={14} className="text-[var(--text-tertiary)]" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {plan.title || plan.goal || 'Plan'}
            </span>
            <span className="text-[10px] uppercase tracking-wide text-[var(--text-tertiary)]">
              {STATUS_LABEL[plan.status] ?? plan.status}
            </span>
          </div>
          {plan.goal && plan.goal !== plan.title && (
            <div className="text-[12px] text-[var(--text-tertiary)] line-clamp-1">
              {plan.goal}
            </div>
          )}
        </div>
        <div className="text-xs text-[var(--text-tertiary)] flex-shrink-0 tabular-nums">
          {stats.completed} / {stats.total}
        </div>
        {collapsed ? (
          <ChevronDown size={16} className="text-[var(--icon-tertiary)] flex-shrink-0" />
        ) : (
          <ChevronUp size={16} className="text-[var(--icon-tertiary)] flex-shrink-0" />
        )}
      </button>

      {!collapsed && (
        <div className="border-t border-[var(--border-light)] py-1 max-h-[40vh] overflow-y-auto">
          {plan.commit_sha && isDone && <PlanVersionBar plan={plan} />}
          {plan.tasks.length === 0 ? (
            <div className="px-4 py-3 text-sm text-[var(--text-tertiary)]">
              No tasks
            </div>
          ) : (
            plan.tasks.map((task, idx) => {
              const isDetail = isDetailRow(task.title)
              if (isDetail) {
                // Mark "is this the last detail in the run?" so the
                // connector line stops cleanly instead of trailing past
                // the row.
                const next = plan.tasks[idx + 1]
                const last = !next || !isDetailRow(next.title)
                return <DetailRow key={task.task_id} task={task} last={last} />
              }
              return <HeaderRow key={task.task_id} task={task} />
            })
          )}
          {plan.error && (
            <div className="mx-3 my-2 px-3 py-2 rounded-md bg-[var(--function-error)]/10 border border-[var(--function-error)]/30 text-[12px] text-[var(--function-error)]">
              {plan.error}
            </div>
          )}
        </div>
      )}
    </div>
  )
}


function PlanVersionBar({ plan }: { plan: PlanEventData }) {
  const navigate = useNavigate()
  const [diff, setDiff] = useState<string | null>(null)
  const [diffOpen, setDiffOpen] = useState(false)
  const [loading, setLoading] = useState(false)
  const [restoring, setRestoring] = useState(false)
  const [forking, setForking] = useState(false)
  const short = plan.commit_sha?.slice(0, 7) ?? ''

  const onViewDiff = async () => {
    if (diffOpen) {
      setDiffOpen(false)
      return
    }
    setDiffOpen(true)
    if (diff !== null) return
    setLoading(true)
    try {
      const r = await getPlanDiff(plan.plan_id)
      setDiff(r.diff || '')
    } catch (e) {
      console.error('plan diff failed', e)
      showErrorToast('Failed to load diff')
      setDiff('')
    } finally {
      setLoading(false)
    }
  }

  const onRestore = async () => {
    if (
      !window.confirm(
        `Restore project to "${plan.title || plan.goal}"? This is destructive — uncommitted changes will be lost.`,
      )
    )
      return
    setRestoring(true)
    try {
      const ok = await restorePlan(plan.plan_id)
      if (ok) showSuccessToast('Project restored to this version')
      else showErrorToast('Restore failed')
    } catch (e) {
      console.error('restore failed', e)
      showErrorToast('Restore failed')
    } finally {
      setRestoring(false)
    }
  }

  const onFork = async () => {
    setForking(true)
    try {
      const newSessionId = await forkPlan(plan.plan_id)
      showSuccessToast('Forked to new session')
      navigate(`/chat/${newSessionId}`)
    } catch (e) {
      console.error('fork failed', e)
      showErrorToast('Fork failed')
    } finally {
      setForking(false)
    }
  }

  const [variantsOpen, setVariantsOpen] = useState(false)

  return (
    <div className="mx-3 my-1 rounded-md border border-[var(--border-light)] bg-[var(--fill-tsp-white-light)]">
      <div className="flex items-center gap-2 px-2.5 py-1.5 text-[12px]">
        <GitCommit size={12} className="text-[var(--text-tertiary)] flex-shrink-0" />
        <span className="font-mono text-[var(--text-secondary)] flex-shrink-0">{short}</span>
        <span className="text-[var(--text-tertiary)]">snapshot</span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onViewDiff}
          className="px-2 h-6 rounded text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-dark)] transition-colors"
        >
          {diffOpen ? 'Hide diff' : 'View diff'}
        </button>
        <button
          type="button"
          onClick={onFork}
          disabled={forking}
          className="px-2 h-6 rounded inline-flex items-center gap-1 text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-dark)] disabled:opacity-50 transition-colors"
          title="Branch a new session from this snapshot"
        >
          <GitBranch size={11} />
          <span>{forking ? 'Forking…' : 'Fork'}</span>
        </button>
        <button
          type="button"
          onClick={() => setVariantsOpen(true)}
          className="px-2 h-6 rounded inline-flex items-center gap-1 text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-dark)] transition-colors"
          title="Spawn N parallel forks for side-by-side compare"
        >
          <Columns3 size={11} />
          <span>Variants</span>
        </button>
        <button
          type="button"
          onClick={onRestore}
          disabled={restoring}
          className="px-2 h-6 rounded inline-flex items-center gap-1 text-[var(--text-secondary)] hover:bg-[var(--fill-tsp-white-dark)] disabled:opacity-50 transition-colors"
          title="Reset project files to this version"
        >
          <RotateCcw size={11} />
          <span>{restoring ? 'Restoring…' : 'Restore'}</span>
        </button>
      </div>
      {diffOpen && (
        <div className="border-t border-[var(--border-light)]">
          {loading ? (
            <div className="px-3 py-2 text-[12px] text-[var(--text-tertiary)]">
              Loading diff…
            </div>
          ) : !diff ? (
            <div className="px-3 py-2 text-[12px] text-[var(--text-tertiary)]">
              No changes recorded for this plan.
            </div>
          ) : (
            <pre className="m-0 px-3 py-2 max-h-[40vh] overflow-auto text-[11.5px] leading-[1.45] font-mono whitespace-pre">
              {diff.split('\n').map((line, i) => {
                const cls =
                  line.startsWith('+') && !line.startsWith('+++')
                    ? 'text-[var(--function-success)]'
                    : line.startsWith('-') && !line.startsWith('---')
                      ? 'text-[var(--function-error)]'
                      : line.startsWith('@@')
                        ? 'text-[var(--text-brand)]'
                        : 'text-[var(--text-secondary)]'
                return (
                  <div key={i} className={cls}>
                    {line || ' '}
                  </div>
                )
              })}
            </pre>
          )}
        </div>
      )}
      <VariantsDialog
        open={variantsOpen}
        onOpenChange={setVariantsOpen}
        planId={plan.plan_id}
        planTitle={plan.title || plan.goal || 'plan'}
      />
    </div>
  )
}


function VariantsDialog({
  open,
  onOpenChange,
  planId,
  planTitle,
}: {
  open: boolean
  onOpenChange: (o: boolean) => void
  planId: string
  planTitle: string
}) {
  const navigate = useNavigate()
  // Default to 3 labeled rows. Each row's label seeds the per-fork
  // project name and labels the column on the compare page; the user
  // hasn't typed an actual prompt yet because the per-variant prompt
  // gets entered in each forked session's chat. Variants is for
  // *parallel* exploration, not predeclared parallel chats.
  const [rows, setRows] = useState<string[]>(['Minimalist', 'Bold', 'Experimental'])
  const [busy, setBusy] = useState(false)

  const setRow = (i: number, v: string) =>
    setRows((prev) => prev.map((r, idx) => (idx === i ? v : r)))

  const onAdd = () => {
    if (rows.length >= 6) return
    setRows((prev) => [...prev, `Variant ${prev.length + 1}`])
  }
  const onRemove = (i: number) => {
    if (rows.length <= 2) return
    setRows((prev) => prev.filter((_, idx) => idx !== i))
  }

  const onSubmit = async () => {
    const labels = rows.map((r) => r.trim()).filter(Boolean)
    if (labels.length < 2) {
      showErrorToast('Need at least 2 labeled variants')
      return
    }
    setBusy(true)
    try {
      const sessions = await forkPlanMany(planId, labels.length, labels)
      const ids = sessions.map((s) => s.session_id).join(',')
      // Round-trip user-controlled labels through base64 so commas /
      // ampersands in the label can't break the URL.
      const enc = sessions
        .map((s) =>
          s.label ? btoa(unescape(encodeURIComponent(s.label))) : '',
        )
        .join(',')
      onOpenChange(false)
      navigate(`/compare?sessions=${ids}&labels=${enc}`)
    } catch (e) {
      console.error('fork-many failed', e)
      showErrorToast('Failed to spawn variants')
    } finally {
      setBusy(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Spawn variants</DialogTitle>
          <DialogDescription>
            Fork "{planTitle}" into 2-6 parallel sessions. Each one gets
            its own sandbox; you'll land on a compare page where you
            can prompt each one differently and pick the winner.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-2 mt-2">
          {rows.map((label, i) => (
            <div key={i} className="flex items-center gap-2">
              <span className="text-[12px] tabular-nums text-[var(--text-tertiary)] w-4">
                {i + 1}
              </span>
              <input
                type="text"
                value={label}
                onChange={(e) => setRow(i, e.target.value)}
                placeholder={`Variant ${i + 1} label`}
                className="flex-1 h-8 px-2 rounded-md text-sm bg-[var(--fill-tsp-white-light)] border border-[var(--border-light)] focus:outline-none focus:ring-1 focus:ring-[var(--text-brand)]"
              />
              <button
                type="button"
                onClick={() => onRemove(i)}
                disabled={rows.length <= 2}
                className="h-7 w-7 inline-flex items-center justify-center rounded-md hover:bg-[var(--fill-tsp-white-light)] text-[var(--icon-secondary)] disabled:opacity-40"
                title="Remove"
              >
                <X size={14} />
              </button>
            </div>
          ))}
          <button
            type="button"
            onClick={onAdd}
            disabled={rows.length >= 6}
            className="self-start text-sm text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:opacity-40"
          >
            + Add variant
          </button>
        </div>
        <DialogFooter>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={busy}
            className="h-9 px-4 rounded-md text-sm font-medium border border-[var(--border-btn-main)] hover:bg-[var(--fill-tsp-white-light)] disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onSubmit}
            disabled={busy}
            className="h-9 px-4 rounded-md text-sm font-medium bg-[var(--text-brand)] text-white hover:opacity-90 disabled:opacity-50 inline-flex items-center gap-1.5"
          >
            {busy && <Loader2 size={14} className="animate-spin" />}
            Spawn {rows.length}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

