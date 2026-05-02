import type { FileInfo } from '@/api/file'

export type AgentSSEEvent = {
  event:
    | 'tool'
    | 'task'
    | 'message'
    | 'error'
    | 'done'
    | 'title'
    | 'wait'
    | 'plan'
    | 'attachments'
  data:
    | ToolEventData
    | TaskEventData
    | MessageEventData
    | ErrorEventData
    | DoneEventData
    | TitleEventData
    | WaitEventData
    | PlanEventData
}

export interface BaseEventData {
  event_id: string
  timestamp: number
}

export interface ToolEventData extends BaseEventData {
  tool_call_id: string
  name: string
  status: 'calling' | 'called'
  function: string
  args: { [key: string]: any }
  content?: any
}

export type TaskStatusValue =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'blocked'

export type PlanStatusValue =
  | 'planning'
  | 'executing'
  | 'completed'
  | 'failed'

export interface TaskEventData extends BaseEventData {
  task_id: string
  plan_id: string
  position: number
  title: string
  details?: string | null
  status: TaskStatusValue
  result?: string | null
  error?: string | null
  retries: number
}

export interface MessageEventData extends BaseEventData {
  content: string
  role: 'user' | 'assistant'
  attachments: FileInfo[]
  // Streaming: when the same logical assistant turn is emitted as multiple
  // MessageEvents (incremental text deltas), they share `message_id`. The
  // FE replaces an existing bubble with the same id instead of appending.
  // The last emit for a turn carries `partial=false`.
  message_id?: string | null
  partial?: boolean
}

export interface ErrorEventData extends BaseEventData {
  error: string
}

export interface DoneEventData extends BaseEventData {}

export interface WaitEventData extends BaseEventData {}

export interface TitleEventData extends BaseEventData {
  title: string
}

export interface PlanEventData extends BaseEventData {
  plan_id: string
  title: string
  goal: string
  status: PlanStatusValue
  error?: string | null
  commit_sha?: string | null
  tasks: TaskEventData[]
}
