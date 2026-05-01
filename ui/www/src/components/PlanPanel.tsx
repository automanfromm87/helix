import { useMemo, useState } from 'react'
import {
  AlertCircle,
  Ban,
  Check,
  ChevronDown,
  ChevronUp,
  Circle,
  Loader2,
} from 'lucide-react'

import Markdown from './Markdown'
import type { PlanEventData, TaskEventData, TaskStatusValue } from '@/types/event'
import { cn } from '@/lib/utils'

interface Props {
  plan: PlanEventData
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
            // Completed tasks: dim slightly + light strikethrough so the
            // user can still read what was done. Avoids the previous "huge
            // wall of struck-through text" look.
            isCompleted && 'text-[var(--text-tertiary)] line-through decoration-[var(--text-tertiary)]/60',
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


export default function PlanPanel({ plan }: Props) {
  const [collapsed, setCollapsed] = useState(false)

  const stats = useMemo(() => {
    const completed = plan.tasks.filter((t) => t.status === 'completed').length
    const total = plan.tasks.length
    return { completed, total }
  }, [plan.tasks])

  const isFailed = plan.status === 'failed'
  const isDone = plan.status === 'completed'
  const isActive = plan.status === 'planning' || plan.status === 'executing'

  return (
    <div className="border border-[var(--border-main)] dark:border-[var(--border-light)] bg-[var(--background-menu-white)] rounded-[12px] shadow-[0px_0px_1px_0px_rgba(0,0,0,0.05),0px_4px_16px_0px_rgba(0,0,0,0.04)]">
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
