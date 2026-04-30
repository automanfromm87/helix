import type { ComponentType } from 'react'
import { Edit3, Globe2, Search, Terminal as TerminalIcon, Wrench } from 'lucide-react'

import ShellToolView from '@/components/toolViews/ShellToolView'
import FileToolView from '@/components/toolViews/FileToolView'
import SearchToolView from '@/components/toolViews/SearchToolView'
import BrowserToolView from '@/components/toolViews/BrowserToolView'
import McpToolView from '@/components/toolViews/McpToolView'
import type { ToolContent } from '@/types/message'

/** Tool function -> i18n key for human-readable description. */
export const TOOL_FUNCTION_MAP: Record<string, string> = {
  shell_exec: 'Executing command',
  shell_view: 'Viewing command output',
  shell_wait: 'Waiting for command completion',
  shell_write_to_process: 'Writing data to process',
  shell_kill_process: 'Terminating process',
  file_read: 'Reading file',
  file_write: 'Writing file',
  file_str_replace: 'Replacing file content',
  file_find_in_content: 'Searching file content',
  file_find_by_name: 'Finding file',
  browser_view: 'Viewing webpage',
  browser_navigate: 'Navigating to webpage',
  browser_restart: 'Restarting browser',
  browser_click: 'Clicking element',
  browser_input: 'Entering text',
  browser_move_mouse: 'Moving mouse',
  browser_press_key: 'Pressing key',
  browser_select_option: 'Selecting option',
  browser_scroll_up: 'Scrolling up',
  browser_scroll_down: 'Scrolling down',
  browser_console_exec: 'Executing JS code',
  browser_console_view: 'Viewing console output',
  info_search_web: 'Searching web',
  message_notify_user: 'Sending notification',
  message_ask_user: 'Asking question',
}

/** Tool function -> primary args key to render alongside the description. */
export const TOOL_FUNCTION_ARG_MAP: Record<string, string> = {
  shell_exec: 'command',
  shell_view: 'shell',
  shell_wait: 'shell',
  shell_write_to_process: 'input',
  shell_kill_process: 'shell',
  file_read: 'file',
  file_write: 'file',
  file_str_replace: 'file',
  file_find_in_content: 'file',
  file_find_by_name: 'path',
  browser_view: 'page',
  browser_navigate: 'url',
  browser_restart: 'url',
  browser_click: 'element',
  browser_input: 'text',
  browser_move_mouse: 'position',
  browser_press_key: 'key',
  browser_select_option: 'option',
  browser_scroll_up: 'page',
  browser_scroll_down: 'page',
  browser_console_exec: 'code',
  browser_console_view: 'console',
  info_search_web: 'query',
  message_notify_user: 'message',
  message_ask_user: 'question',
}

/** Tool category -> display name (i18n key). */
export const TOOL_NAME_MAP: Record<string, string> = {
  shell: 'Terminal',
  file: 'File',
  browser: 'Browser',
  info: 'Information',
  message: 'Message',
  mcp: 'MCP Tool',
}

/** Tool category -> icon component. Loose typing to support both lucide-react and custom SVG icons. */
export const TOOL_ICON_MAP: Record<string, ComponentType<any>> = {
  shell: TerminalIcon,
  file: Edit3,
  browser: Globe2,
  search: Search,
  message: Wrench,
  mcp: Wrench,
}

/** Tool category -> right-panel view component. */
export const TOOL_COMPONENT_MAP: Record<string, ComponentType<ToolViewProps>> = {
  shell: ShellToolView,
  file: FileToolView,
  search: SearchToolView,
  browser: BrowserToolView,
  mcp: McpToolView,
}

export interface ToolViewProps {
  sessionId: string
  toolContent: ToolContent
  live: boolean
  isShare?: boolean
}
