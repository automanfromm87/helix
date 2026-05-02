import { useEffect, useRef } from 'react'
import { Check, GitCommit, Loader2, X } from 'lucide-react'

import type { PlanEventData } from '@/types/event'
import { cn } from '@/lib/utils'

interface Props {
  plans: PlanEventData[]
  /** Index into `plans`. 0 = newest, last = oldest. */
  activeIndex: number
  onSelect: (index: number) => void
}

/**
 * Horizontal strip of plan nodes — the session's "git log" rendered
 * inline. Each plan is a node with its status color + title; clicking
 * scrolls history navigation to that plan, mirroring what the
 * `<PlanPanel>` arrows already do but making *all* steps visible at
 * once.
 *
 * Why this earns its sticky-bar slot. Pre-timeline you could only see
 * one plan at a time and the only way to step through history was the
 * tiny arrow buttons inside the panel. With many plans (forks, follow-
 * ups, restores) this turned the most distinctive feature of the
 * product — version-controlled chat — invisible. The timeline puts
 * the version graph front and center: at a glance the user sees how
 * many turns the agent has taken, which ones committed real changes
 * (`commit_sha`), which failed, and which one they're currently
 * looking at.
 *
 * Layout: NEWEST plan on the right (matches how planHistory is
 * indexed: 0 = newest, so we reverse-iterate). Auto-scrolls the
 * active node into view on selection so deep history doesn't
 * silently drift off-screen.
 */
export default function PlanTimeline({ plans, activeIndex, onSelect }: Props) {
  const trackRef = useRef<HTMLDivElement>(null)
  const activeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    activeRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'nearest',
      inline: 'center',
    })
  }, [activeIndex])

  if (plans.length <= 1) return null

  // Render oldest -> newest left-to-right so the user reads the story
  // chronologically. planHistory's 0=newest convention is preserved
  // for callers; we just flip presentation.
  const ordered = plans.map((p, i) => ({ plan: p, index: i })).reverse()

  return (
    <div
      ref={trackRef}
      className="flex items-center gap-0 overflow-x-auto pb-1 -mx-2 px-2 scrollbar-thin"
    >
      {ordered.map(({ plan, index }, i) => {
        const isActive = index === activeIndex
        const isLast = i === ordered.length - 1
        return (
          <div
            key={plan.plan_id}
            className="flex items-center flex-shrink-0"
          >
            <PlanNode
              plan={plan}
              isActive={isActive}
              onClick={() => onSelect(index)}
              ref={isActive ? activeRef : undefined}
            />
            {!isLast && (
              <div
                className="h-px w-4 flex-shrink-0 bg-[var(--border-main)]"
                aria-hidden
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

interface NodeProps {
  plan: PlanEventData
  isActive: boolean
  onClick: () => void
}

const PlanNode = ({
  plan,
  isActive,
  onClick,
  ref,
}: NodeProps & { ref?: React.Ref<HTMLButtonElement> }) => {
  const StatusIcon =
    plan.status === 'completed' ? Check :
    plan.status === 'failed' ? X :
    plan.status === 'executing' || plan.status === 'planning' ? Loader2 :
    GitCommit

  const statusColor =
    plan.status === 'completed' ? 'bg-[var(--function-success)] text-white' :
    plan.status === 'failed' ? 'bg-[var(--function-error)] text-white' :
    plan.status === 'executing' || plan.status === 'planning' ? 'bg-[var(--text-brand)] text-white' :
    'bg-[var(--fill-tsp-gray-main)] text-[var(--icon-secondary)]'

  const isSpinning = plan.status === 'executing' || plan.status === 'planning'

  // The displayed label: prefer `title`, fall back to first task's title,
  // fall back to commit short hash. Keeps the strip readable for plans
  // that the planner didn't title (rare but possible during partial
  // streams).
  const label =
    plan.title?.trim() ||
    plan.tasks?.[0]?.title?.trim() ||
    plan.commit_sha?.slice(0, 7) ||
    'Plan'

  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      title={`${label}${plan.commit_sha ? ` · ${plan.commit_sha.slice(0, 7)}` : ''}`}
      className={cn(
        'group flex flex-col items-center gap-1 px-2 py-1 rounded-md transition-colors flex-shrink-0',
        isActive
          ? 'bg-[var(--fill-tsp-white-main)]'
          : 'hover:bg-[var(--fill-tsp-white-light)]',
      )}
    >
      <div
        className={cn(
          'flex items-center justify-center w-6 h-6 rounded-full transition-shadow',
          statusColor,
          isActive && 'ring-2 ring-offset-2 ring-offset-[var(--background-gray-main)] ring-[var(--text-brand)]',
        )}
      >
        <StatusIcon size={12} className={isSpinning ? 'animate-spin' : ''} />
      </div>
      <span
        className={cn(
          'text-[11px] max-w-[112px] truncate leading-tight',
          isActive ? 'text-[var(--text-primary)] font-medium' : 'text-[var(--text-tertiary)]',
        )}
      >
        {label}
      </span>
    </button>
  )
}
