import type { FileInfo } from '@/api/file'
import type { TaskStatusValue } from '@/types/event'

export type MessageType = 'user' | 'assistant' | 'tool' | 'task' | 'attachments'

export interface Message {
  type: MessageType
  content: BaseContent
}

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

export function isConsecutiveAssistant(messages: Message[], index: number): boolean {
  if (index <= 0) return false
  const isAst = (m: Message) =>
    m.type === 'assistant' ||
    (m.type === 'attachments' && (m.content as AttachmentsContent).role === 'assistant')
  return isAst(messages[index]) && isAst(messages[index - 1])
}
