import type { ToolViewProps } from '@/constants/tool'

interface SearchResult {
  link: string
  title: string
  snippet: string
}

export default function SearchToolView({ toolContent }: ToolViewProps) {
  const results: SearchResult[] = toolContent.content?.results ?? []
  return (
    <>
      <div className="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
            Search
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-y-auto">
        <div className="flex-1 min-h-0 max-w-[640px] mx-auto">
          <div className="flex flex-col overflow-auto h-full px-4 py-3">
            {results.length === 0 ? (
              <div className="flex flex-col items-center justify-center gap-2 py-10 text-[var(--text-tertiary)]">
                <div className="text-sm">No search results captured</div>
                {toolContent?.args?.query && (
                  <div className="text-xs font-mono">{String(toolContent.args.query)}</div>
                )}
              </div>
            ) : (
              results.map((r, i) => (
                <div key={i} className="py-3 pt-0 border-b border-[var(--border-light)]">
                  <a
                    href={r.link}
                    target="_blank"
                    rel="noreferrer"
                    className="block text-[var(--text-primary)] text-sm font-medium hover:underline line-clamp-2 cursor-pointer"
                  >
                    {r.title}
                  </a>
                  <div className="text-[var(--text-tertiary)] text-xs mt-0.5 line-clamp-3">
                    {r.snippet}
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </>
  )
}
