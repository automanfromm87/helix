import type {
  ErrorEventData,
  MessageEventData,
  TaskEventData,
  ToolEventData,
} from '@/types/event'
import type {
  AttachmentsContent,
  Message,
  MessageContent,
  TaskContent,
  ToolContent,
} from '@/types/message'

/**
 * Pure-function reducers for the chat message list. Lifted out of the
 * useChatStream hook so they can be unit-tested without React, and so the
 * narrowing on Message's discriminated union shows up explicitly.
 *
 * Every function returns a fresh array — never mutates `prev`. The hook
 * threads them through setMessages((prev) => reduce*(prev, data)).
 */

const isPlaceholderEventId = (id?: string): boolean => !id || /^[0-]+$/.test(id)

/**
 * Streaming/dedupe semantics:
 *  - Same `message_id` ⇒ replace the prior partial bubble in place (the
 *    final emit carries `partial=false` and freezes the text).
 *  - Same non-placeholder `event_id` ⇒ replace, so server replay overlap
 *    or multi-agent acks don't trip React's duplicate-key warning.
 *  - Otherwise ⇒ append; if the message carries attachments, append an
 *    extra attachments row right after.
 */
export function reduceMessage(prev: Message[], data: MessageEventData): Message[] {
  // Coerce role: a less-careful backend (or a future system-role event)
  // could send something outside the user|assistant union. Falling back
  // to 'assistant' keeps the bubble visible instead of creating a
  // phantom row whose type is technically invalid.
  const role: 'user' | 'assistant' =
    data.role === 'user' || data.role === 'assistant' ? data.role : 'assistant'
  const matchByMessageId = (m: Message): boolean => {
    if (m.type !== role) return false
    if (m.type !== 'user' && m.type !== 'assistant') return false
    return data.message_id != null && m.content.message_id === data.message_id
  }
  if (data.message_id) {
    const idx = prev.findIndex(matchByMessageId)
    if (idx >= 0) {
      const next = prev.slice()
      next[idx] = { type: role, content: { ...data } satisfies MessageContent }
      return next
    }
  }

  if (!isPlaceholderEventId(data.event_id)) {
    const idx = prev.findIndex((m) => {
      if (m.type !== role) return false
      if (m.type !== 'user' && m.type !== 'assistant') return false
      return m.content.event_id === data.event_id
    })
    if (idx >= 0) {
      const next = prev.slice()
      next[idx] = { type: role, content: { ...data } satisfies MessageContent }
      return next
    }
  }

  const next: Message[] = [
    ...prev,
    { type: role, content: { ...data } satisfies MessageContent },
  ]
  // Type says `FileInfo[] | null | undefined`, but a less-careful backend
  // serializer could send a string or object. Array.isArray is the only
  // honest check.
  if (Array.isArray(data.attachments) && data.attachments.length > 0) {
    next.push({ type: 'attachments', content: { ...data } as AttachmentsContent })
  }
  return next
}

/**
 * Tool event placement, in priority:
 *  1. Existing top-level tool row with the same tool_call_id ⇒ replace
 *  2. A tool inside the trailing running task's tools[] ⇒ replace
 *  3. The trailing running task ⇒ append into its tools[]
 *  4. Else ⇒ append a new top-level tool row
 */
export function reduceTool(prev: Message[], data: ToolEventData): Message[] {
  const tool: ToolContent = { ...data }

  const directIdx = prev.findIndex(
    (m) => m.type === 'tool' && m.content.tool_call_id === tool.tool_call_id,
  )
  if (directIdx >= 0) {
    const next = prev.slice()
    next[directIdx] = { type: 'tool', content: tool }
    return next
  }

  for (let i = prev.length - 1; i >= 0; i--) {
    const m = prev[i]
    if (m.type !== 'task') continue
    const task = m.content
    const toolIdx = task.tools.findIndex((t) => t.tool_call_id === tool.tool_call_id)
    if (toolIdx >= 0) {
      const nextTools = task.tools.slice()
      nextTools[toolIdx] = tool
      const next = prev.slice()
      next[i] = { type: 'task', content: { ...task, tools: nextTools } }
      return next
    }
    if (task.status === 'running') {
      const next = prev.slice()
      next[i] = { type: 'task', content: { ...task, tools: [...task.tools, tool] } }
      return next
    }
    break
  }

  return [...prev, { type: 'tool', content: tool }]
}

/**
 * Task event upsert: matched by task_id. Updates merge with the existing
 * row (preserving accumulated `tools[]`, falling back to existing values
 * for absent fields). New tasks start with an empty `tools[]`.
 */
export function reduceTask(prev: Message[], data: TaskEventData): Message[] {
  const idx = prev.findIndex(
    (m) => m.type === 'task' && m.content.task_id === data.task_id,
  )
  if (idx >= 0) {
    const row = prev[idx]
    if (row.type !== 'task') return prev
    const existing = row.content
    const next = prev.slice()
    next[idx] = {
      type: 'task',
      content: {
        ...existing,
        status: data.status,
        title: data.title,
        details: data.details ?? existing.details,
        result: data.result ?? existing.result,
        error: data.error ?? existing.error,
      },
    }
    return next
  }
  const fresh: TaskContent = {
    task_id: data.task_id,
    plan_id: data.plan_id,
    position: data.position,
    title: data.title,
    details: data.details ?? null,
    status: data.status,
    result: data.result ?? null,
    error: data.error ?? null,
    tools: [],
    timestamp: data.timestamp,
  }
  return [...prev, { type: 'task', content: fresh }]
}

/**
 * Surface error events as a marked-up assistant bubble. The event_id keeps
 * the row dedupe-able by the same machinery as normal assistant messages.
 */
export function reduceError(prev: Message[], data: ErrorEventData): Message[] {
  return [
    ...prev,
    {
      type: 'assistant',
      content: {
        event_id: data.event_id,
        content: `**⚠️ Error**\n\n${data.error}`,
        timestamp: data.timestamp,
      },
    },
  ]
}

/** Truncate the message list at the user message with the given event_id. */
export function reduceTruncateAtUserEvent(prev: Message[], eventId: string): Message[] {
  const idx = prev.findIndex(
    (m) => m.type === 'user' && m.content.event_id === eventId,
  )
  return idx >= 0 ? prev.slice(0, idx) : prev
}

/** Append a user-typed message bubble. */
export function reduceAppendUserMessage(
  prev: Message[],
  message: string,
  timestamp: number,
): Message[] {
  return [
    ...prev,
    { type: 'user', content: { content: message, timestamp } },
  ]
}

/** Append an attachments row tied to the most-recent user turn. */
export function reduceAppendUserAttachments(
  prev: Message[],
  attachments: AttachmentsContent['attachments'],
  timestamp: number,
): Message[] {
  return [
    ...prev,
    {
      type: 'attachments',
      content: { role: 'user', attachments, timestamp },
    },
  ]
}
