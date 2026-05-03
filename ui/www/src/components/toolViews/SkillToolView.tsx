import Markdown from '@/components/Markdown'
import type { ToolViewProps } from '@/constants/tool'

/**
 * Side-panel view for `load_skill` tool calls. The body lives on the
 * tool_content as markdown; render it as-is so the user can read what
 * the agent loaded into context. Defends against minor model output
 * weirdness (non-string body, missing content) by falling back to a
 * placeholder rather than throwing.
 */
export default function SkillToolView({ toolContent }: ToolViewProps) {
  const c = toolContent.content as { name?: unknown; body?: unknown } | undefined
  const name = typeof c?.name === 'string' && c.name ? c.name : 'skill'
  const body =
    typeof c?.body === 'string' && c.body
      ? c.body
      : '_(skill body unavailable — the loader call did not return a body)_'

  return (
    <div className="flex flex-col h-full w-full">
      <div className="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-[300px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
            Skill: {name}
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 overflow-auto px-4 py-3">
        <Markdown
          content={body}
          className="prose prose-sm dark:prose-invert max-w-none [&_pre:not(.shiki)]:!bg-[var(--fill-tsp-white-light)] [&_pre:not(.shiki)]:text-[var(--text-primary)]"
        />
      </div>
    </div>
  )
}
