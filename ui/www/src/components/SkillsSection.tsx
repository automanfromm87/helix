import { useEffect, useState } from 'react'
import { ChevronDown, Sparkles } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from './ui/Dialog'
import { listSkills } from '@/api/skills'
import type { SkillItem } from '@/types/response'
import { cn } from '@/lib/utils'

const SOURCE_LABEL: Record<SkillItem['source'], string> = {
  file: 'built-in',
  global: 'global',
  project: 'project',
}

const SOURCE_BADGE_COLOR: Record<SkillItem['source'], string> = {
  file: 'bg-[var(--fill-tsp-gray-main)] text-[var(--text-tertiary)]',
  global: 'bg-[var(--fill-tsp-blue-light)] text-[var(--function-link)]',
  project: 'bg-[var(--fill-tsp-green-light)] text-[var(--function-success)]',
}

export default function SkillsSection() {
  const [skills, setSkills] = useState<SkillItem[]>([])
  const [open, setOpen] = useState(true)
  const [active, setActive] = useState<SkillItem | null>(null)

  useEffect(() => {
    void listSkills()
      .then((res) => setSkills(res.skills))
      .catch((e) => console.error('Failed to fetch skills:', e))
  }, [])

  // Empty registry → render nothing rather than an empty stub. The agent
  // still works without skills; the section only earns its sidebar slot
  // when there's at least one to surface.
  if (skills.length === 0) return null

  return (
    <>
      <div className="flex flex-col mt-[4px]">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="flex items-center w-full gap-[12px] h-[36px] ps-[9px] pe-[6px] rounded-[10px] hover:bg-[var(--fill-tsp-white-light)] transition-colors"
        >
          <div className="shrink-0 size-[18px] flex items-center justify-center">
            <Sparkles size={18} className="text-[var(--text-primary)]" />
          </div>
          <span className="flex-1 min-w-0 text-left text-[14px] text-[var(--text-primary)]">
            Skills
          </span>
          <span className="text-[12px] text-[var(--text-tertiary)] tabular-nums">
            {skills.length}
          </span>
          <ChevronDown
            size={14}
            className={cn(
              'text-[var(--icon-secondary)] transition-transform',
              !open && '-rotate-90',
            )}
          />
        </button>

        {open && (
          <div className="flex flex-col gap-px mt-[2px]">
            {skills.map((skill) => (
              <button
                key={`${skill.source}:${skill.name}`}
                type="button"
                onClick={() => setActive(skill)}
                className="flex items-center gap-[8px] h-[30px] ps-[36px] pe-[6px] rounded-[8px] hover:bg-[var(--fill-tsp-white-light)] transition-colors text-left"
                title={skill.description}
              >
                <span className="flex-1 min-w-0 truncate text-[13px] text-[var(--text-secondary)]">
                  {skill.name}
                </span>
                <span
                  className={cn(
                    'shrink-0 px-[6px] py-[1px] rounded-full text-[10px] font-medium uppercase tracking-wide',
                    SOURCE_BADGE_COLOR[skill.source],
                  )}
                >
                  {SOURCE_LABEL[skill.source]}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>

      <Dialog
        open={active !== null}
        onOpenChange={(o) => (o ? null : setActive(null))}
      >
        <DialogContent className="max-w-2xl max-h-[80vh] flex flex-col">
          {active && (
            <>
              <DialogHeader>
                <DialogTitle className="flex items-center gap-2">
                  <Sparkles
                    size={16}
                    className="text-[var(--text-primary)] shrink-0"
                  />
                  {active.name}
                  <span
                    className={cn(
                      'px-[6px] py-[1px] rounded-full text-[10px] font-medium uppercase tracking-wide',
                      SOURCE_BADGE_COLOR[active.source],
                    )}
                  >
                    {SOURCE_LABEL[active.source]}
                  </span>
                </DialogTitle>
                <DialogDescription className="whitespace-pre-line">
                  {active.description}
                </DialogDescription>
              </DialogHeader>
              <div className="flex-1 min-h-0 overflow-auto rounded-md border border-[var(--border-main)] bg-[var(--background-gray-main)] p-3">
                <pre className="text-xs whitespace-pre-wrap font-mono text-[var(--text-primary)]">
                  {active.body}
                </pre>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </>
  )
}
