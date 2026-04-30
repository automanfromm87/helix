import { useMemo } from 'react'
import type { ComponentType } from 'react'

import {
  TOOL_COMPONENT_MAP,
  TOOL_FUNCTION_ARG_MAP,
  TOOL_FUNCTION_MAP,
  TOOL_ICON_MAP,
  TOOL_NAME_MAP,
  type ToolViewProps,
} from '@/constants/tool'
import type { ToolContent } from '@/types/message'

export interface ToolInfo {
  Icon: ComponentType<any> | null
  name: string
  function: string
  functionArg: string
  View: ComponentType<ToolViewProps> | null
}

export function useToolInfo(tool: ToolContent | undefined): ToolInfo | null {
  return useMemo(() => {
    if (!tool) return null

    if (tool.function.startsWith('mcp_')) {
      const mcpToolName = tool.function.replace(/^mcp_/, '')
      let functionArg = ''
      const args = tool.args
      if (args && Object.keys(args).length > 0) {
        const firstKey = Object.keys(args)[0]
        const firstValue = args[firstKey]
        if (typeof firstValue === 'string' && firstValue.length < 50) {
          functionArg = firstValue
        } else if (firstValue !== undefined) {
          functionArg = JSON.stringify(firstValue).substring(0, 30) + '...'
        }
      }
      return {
        Icon: TOOL_ICON_MAP['mcp'] ?? null,
        name: TOOL_NAME_MAP['mcp'] || 'MCP Tool',
        function: mcpToolName,
        functionArg,
        View: TOOL_COMPONENT_MAP['mcp'] ?? null,
      }
    }

    let functionArg = tool.args[TOOL_FUNCTION_ARG_MAP[tool.function]] || ''
    if (TOOL_FUNCTION_ARG_MAP[tool.function] === 'file' && typeof functionArg === 'string') {
      functionArg = functionArg.replace(/^\/home\/ubuntu\//, '')
    }

    return {
      Icon: TOOL_ICON_MAP[tool.name] ?? null,
      name: TOOL_NAME_MAP[tool.name] || '',
      function: TOOL_FUNCTION_MAP[tool.function] || tool.function,
      functionArg,
      View: TOOL_COMPONENT_MAP[tool.name] ?? null,
    }
  }, [tool])
}
