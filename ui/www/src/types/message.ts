import type { FileInfo } from '@/api/file'
import type { TaskStatusValue } from '@/types/event'

export interface BaseContent {
  timestamp: number
}

export interface MessageContent extends BaseContent {
  event_id?: string
  content: string
  attachments?: FileInfo[] | null
  message_id?: string | null
  partial?: boolean
}

export interface ToolContent extends BaseContent {
  tool_call_id: string
  name: string
  function: string
  // Tool args/content are JSON payloads of arbitrary shape determined by the
  // tool itself — keep them as `any` so individual ToolView components can
  // access ad-hoc fields without a forest of casts. Stronger typing belongs
  // per-tool, not on the shared shape.
  args: any
  content?: any
  status: 'calling' | 'called'
}

export interface TaskContent extends BaseContent {
  task_id: string
  plan_id: string
  position: number
  title: string
  details?: string | null
  status: TaskStatusValue
  result?: string | null
  error?: string | null
  tools: ToolContent[]
}

export interface AttachmentsContent extends BaseContent {
  role: 'user' | 'assistant'
  attachments: FileInfo[]
}

/**
 * Discriminated union over message rows. Narrowing on `m.type` gives full
 * static access to the matching content shape, replacing the old pattern
 * of `m.content as TaskContent` casts scattered through reducers + render
 * code.
 */
export type Message =
  | { type: 'user' | 'assistant'; content: MessageContent }
  | { type: 'tool'; content: ToolContent }
  | { type: 'task'; content: TaskContent }
  | { type: 'attachments'; content: AttachmentsContent }

export type MessageType = Message['type']

export function isConsecutiveAssistant(messages: Message[], index: number): boolean {
  if (index <= 0) return false
  const isAst = (m: Message) =>
    m.type === 'assistant' ||
    (m.type === 'attachments' && m.content.role === 'assistant')
  if (!isAst(messages[index])) return false
  // Skip past tool/task separators — they belong to the same Helix turn,
  // so the assistant message after them shouldn't re-render the header.
  // Without this, plan-act runs render duplicate "Helix" headers around
  // every task block.
  for (let i = index - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.type === 'tool' || m.type === 'task') continue
    if (m.type === 'user') return false
    return isAst(m)
  }
  return false
}
