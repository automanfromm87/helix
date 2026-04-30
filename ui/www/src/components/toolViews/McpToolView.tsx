import type { ToolViewProps } from '@/constants/tool'

export default function McpToolView({ toolContent }: ToolViewProps) {
  const args = toolContent.args
  const result = toolContent.content?.result

  return (
    <>
      <div className="h-[36px] flex items-center px-3 w-full bg-[var(--background-gray-main)] border-b border-[var(--border-main)] rounded-t-[12px] shadow-[inset_0px_1px_0px_0px_#FFFFFF] dark:shadow-[inset_0px_1px_0px_0px_#FFFFFF30]">
        <div className="flex-1 flex items-center justify-center">
          <div className="max-w-[250px] truncate text-[var(--text-tertiary)] text-sm font-medium text-center">
            MCP Tool
          </div>
        </div>
      </div>
      <div className="flex-1 min-h-0 w-full overflow-y-auto">
        <div className="flex-1 min-h-0 max-w-[640px] mx-auto">
          <div className="flex flex-col overflow-auto h-full px-4 py-3">
            <div className="py-3 pt-0">
              <div className="text-[var(--text-primary)] text-sm font-medium mb-2">
                Tool: {toolContent.function}
              </div>
              {args && Object.keys(args).length > 0 && (
                <div className="mb-4">
                  <div className="text-[var(--text-primary)] text-sm font-medium mb-2">
                    Arguments:
                  </div>
                  <pre className="bg-[var(--fill-tsp-gray-main)] rounded-lg p-3 text-xs text-[var(--text-secondary)] overflow-x-auto">
                    <code>{JSON.stringify(args, null, 2)}</code>
                  </pre>
                </div>
              )}
              {result ? (
                <div className="mb-4">
                  <div className="text-[var(--text-primary)] text-sm font-medium mb-2">
                    Result:
                  </div>
                  <div className="bg-[var(--fill-tsp-gray-main)] rounded-lg p-3 text-sm text-[var(--text-secondary)] whitespace-pre-wrap">
                    {result}
                  </div>
                </div>
              ) : (
                <div className="text-[var(--text-tertiary)] text-sm">
                  {toolContent.status === 'calling'
                    ? 'Tool is executing...'
                    : 'Waiting for result...'}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
