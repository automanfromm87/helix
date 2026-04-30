import { useMemo, useState } from 'react'
import { AlertCircle, Ban, Check, ChevronDown, ChevronRight, ChevronUp, Clock, Loader2 } from 'lucide-react'

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

function TaskIcon({ status }: { status: TaskStatusValue }) {
  switch (status) {
    case 'running':
      return (
        <Loader2
          size={16}
          className="text-[var(--text-brand)] animate-spin flex-shrink-0"
        />
      )
    case 'completed':
      return (
        <div className="size-4 rounded-full bg-[var(--function-success)] flex items-center justify-center flex-shrink-0">
          <Check size={10} className="text-white" />
        </div>
      )
    case 'failed':
      return (
        <div className="size-4 rounded-full bg-[var(--function-error)] flex items-center justify-center flex-shrink-0">
          <AlertCircle size={10} className="text-white" />
        </div>
      )
    case 'blocked':
      return <Ban size={14} className="text-[var(--text-tertiary)] flex-shrink-0" />
    case 'pending':
    default:
      return <Clock size={14} className="text-[var(--text-tertiary)] flex-shrink-0" />
  }
}

function TaskRow({ task }: { task: TaskEventData }) {
  const dim = task.status === 'pending' || task.status === 'blocked'
  const [expanded, setExpanded] = useState(false)
  const hasDetails = Boolean(task.details && task.details.trim())
  return (
    <div
      className={cn(
        'flex items-start gap-2 py-1.5 px-3 rounded-md transition-colors',
        task.status === 'running' && 'bg-[var(--fill-tsp-white-light)]',
      )}
      title={task.error || task.title}
    >
      <div className="pt-0.5">
        <TaskIcon status={task.status} />
      </div>
      <div className="flex-1 min-w-0">
        <div
          className={cn(
            'flex items-center gap-1 text-sm leading-tight',
            dim ? 'text-[var(--text-tertiary)]' : 'text-[var(--text-primary)]',
            task.status === 'completed' && 'line-through opacity-70',
          )}
        >
          {hasDetails && (
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="flex-shrink-0 text-[var(--icon-tertiary)] hover:text-[var(--text-primary)]"
              aria-label={expanded ? 'Collapse details' : 'Expand details'}
            >
              {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
            </button>
          )}
          <span className={cn('font-medium', !hasDetails && 'ms-[16px]')}>
            {task.title}
          </span>
        </div>
        {hasDetails && expanded && (
          <div className="ms-[16px] mt-1 mb-1 text-[12px] text-[var(--text-secondary)] markdown-content">
            <Markdown content={task.details ?? ''} />
          </div>
        )}
        {task.error && (
          <div className="ms-[16px] text-[12px] mt-0.5 text-[var(--function-error)] truncate">
            {task.error}
          </div>
        )}
      </div>
      {task.retries > 0 && (
        <div
          className="text-[11px] text-[var(--text-tertiary)] flex-shrink-0 pt-0.5"
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
              <Check size={10} className="text-white" />
            </div>
          ) : (
            <Clock size={16} className="text-[var(--text-tertiary)]" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-semibold text-[var(--text-primary)] truncate">
              {plan.title || plan.goal || 'Plan'}
            </span>
            <span className="text-[11px] uppercase tracking-wide text-[var(--text-tertiary)]">
              {STATUS_LABEL[plan.status] ?? plan.status}
            </span>
          </div>
          {plan.goal && plan.goal !== plan.title && (
            <div className="text-[12px] text-[var(--text-tertiary)] truncate">
              {plan.goal}
            </div>
          )}
        </div>
        <div className="text-xs text-[var(--text-tertiary)] flex-shrink-0">
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
            plan.tasks.map((task) => (
              <TaskRow key={task.task_id} task={task} />
            ))
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
