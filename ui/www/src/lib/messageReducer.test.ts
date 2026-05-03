import { describe, expect, it } from 'vitest'

import type {
  ErrorEventData,
  MessageEventData,
  TaskEventData,
  ToolEventData,
} from '@/types/event'
import type { Message, TaskContent } from '@/types/message'

import {
  reduceAppendUserAttachments,
  reduceAppendUserMessage,
  reduceError,
  reduceMessage,
  reduceTask,
  reduceTool,
  reduceTruncateAtUserEvent,
} from './messageReducer'

const msg = (
  partial: Partial<MessageEventData> & Pick<MessageEventData, 'role'>,
): MessageEventData => ({
  event_id: 'evt-1',
  timestamp: 1700000000,
  content: 'hello',
  attachments: [],
  ...partial,
})

const tool = (partial: Partial<ToolEventData> = {}): ToolEventData => ({
  event_id: 'evt-tool',
  timestamp: 1700000000,
  tool_call_id: 'call-1',
  name: 'shell',
  status: 'calling',
  function: 'run',
  args: {},
  ...partial,
})

const task = (partial: Partial<TaskEventData> = {}): TaskEventData => ({
  event_id: 'evt-task',
  timestamp: 1700000000,
  task_id: 'task-1',
  plan_id: 'plan-1',
  position: 0,
  title: 'first',
  status: 'running',
  retries: 0,
  ...partial,
})

const taskRow = (partial: Partial<TaskContent> = {}): Message => ({
  type: 'task',
  content: {
    task_id: 'task-1',
    plan_id: 'plan-1',
    position: 0,
    title: 'first',
    details: null,
    status: 'running',
    result: null,
    error: null,
    tools: [],
    timestamp: 1700000000,
    ...partial,
  } as TaskContent,
})

describe('reduceMessage', () => {
  it('appends a fresh assistant bubble', () => {
    const next = reduceMessage([], msg({ role: 'assistant' }))
    expect(next).toHaveLength(1)
    expect(next[0].type).toBe('assistant')
  })

  it('replaces an in-flight partial when message_id matches', () => {
    let state: Message[] = []
    state = reduceMessage(state, msg({
      role: 'assistant',
      message_id: 'm-42',
      content: 'Hel',
      partial: true,
    }))
    state = reduceMessage(state, msg({
      role: 'assistant',
      message_id: 'm-42',
      content: 'Hello world',
      partial: false,
    }))
    expect(state).toHaveLength(1)
    expect(state[0].type).toBe('assistant')
    if (state[0].type === 'assistant') {
      expect(state[0].content.content).toBe('Hello world')
      expect(state[0].content.partial).toBe(false)
    }
  })

  it('does not mutate prev', () => {
    const prev: Message[] = []
    const next = reduceMessage(prev, msg({ role: 'user' }))
    expect(prev).not.toBe(next)
    expect(prev).toHaveLength(0)
  })

  it('dedupes by event_id when no message_id', () => {
    let state: Message[] = []
    state = reduceMessage(state, msg({
      role: 'assistant',
      event_id: 'evt-A',
      content: 'first',
    }))
    state = reduceMessage(state, msg({
      role: 'assistant',
      event_id: 'evt-A',
      content: 'second',
    }))
    expect(state).toHaveLength(1)
  })

  it('treats placeholder event_ids as unique', () => {
    // Both regression cases for the placeholder bug we just fixed:
    // all-zero string and the nil-UUID form.
    const placeholders = ['00000000', '00000000-0000-0000-0000-000000000000']
    for (const p of placeholders) {
      let state: Message[] = []
      state = reduceMessage(state, msg({ role: 'assistant', event_id: p, content: 'A' }))
      state = reduceMessage(state, msg({ role: 'assistant', event_id: p, content: 'B' }))
      expect(state, `placeholder ${p} should not collapse rows`).toHaveLength(2)
    }
  })

  it('appends an attachments row when the message carries attachments', () => {
    const next = reduceMessage(
      [],
      msg({
        role: 'user',
        attachments: [
          {
            file_id: 'f1',
            filename: 'a.txt',
            content_type: 'text/plain',
            size: 10,
            upload_date: '2026',
          },
        ],
      }),
    )
    expect(next.map((m) => m.type)).toEqual(['user', 'attachments'])
  })
})

describe('reduceTool', () => {
  it('appends a top-level tool when no task is running', () => {
    const next = reduceTool([], tool())
    expect(next.map((m) => m.type)).toEqual(['tool'])
  })

  it('attaches the tool to the trailing running task', () => {
    const prev: Message[] = [taskRow({ status: 'running' })]
    const next = reduceTool(prev, tool())
    expect(next).toHaveLength(1)
    expect(next[0].type).toBe('task')
    if (next[0].type === 'task') {
      expect(next[0].content.tools).toHaveLength(1)
      expect(next[0].content.tools[0].tool_call_id).toBe('call-1')
    }
  })

  it('replaces a tool by id without mutating prev rows', () => {
    const prev: Message[] = [
      taskRow({ status: 'running', tools: [{ ...tool(), status: 'calling' }] }),
    ]
    const next = reduceTool(prev, tool({ status: 'called' }))
    if (next[0].type === 'task' && prev[0].type === 'task') {
      expect(next[0].content.tools[0].status).toBe('called')
      // prev row must remain untouched (immutability)
      expect(prev[0].content.tools[0].status).toBe('calling')
      expect(next[0].content.tools).not.toBe(prev[0].content.tools)
    }
  })

  it('does not attach to a non-running trailing task', () => {
    const prev: Message[] = [taskRow({ status: 'completed' })]
    const next = reduceTool(prev, tool())
    expect(next).toHaveLength(2)
    expect(next[1].type).toBe('tool')
  })
})

describe('reduceTask', () => {
  it('appends a new task row', () => {
    const next = reduceTask([], task())
    expect(next).toHaveLength(1)
    if (next[0].type === 'task') {
      expect(next[0].content.tools).toEqual([])
    }
  })

  it('updates an existing task by id without losing tools[]', () => {
    const prev: Message[] = [
      taskRow({ status: 'running', tools: [{ ...tool(), status: 'called' }] }),
    ]
    const next = reduceTask(prev, task({ status: 'completed', title: 'first (done)' }))
    if (next[0].type === 'task') {
      expect(next[0].content.status).toBe('completed')
      expect(next[0].content.title).toBe('first (done)')
      expect(next[0].content.tools).toHaveLength(1)
    }
  })

  it('does not mutate prev', () => {
    const prev: Message[] = [taskRow({ status: 'running' })]
    const next = reduceTask(prev, task({ status: 'completed' }))
    expect(next[0]).not.toBe(prev[0])
    if (prev[0].type === 'task') expect(prev[0].content.status).toBe('running')
  })
})

describe('reduceError', () => {
  it('surfaces the error as an assistant bubble carrying the event_id', () => {
    const data: ErrorEventData = {
      event_id: 'err-1',
      timestamp: 1700000000,
      error: 'boom',
    }
    const next = reduceError([], data)
    expect(next).toHaveLength(1)
    if (next[0].type === 'assistant') {
      expect(next[0].content.event_id).toBe('err-1')
      expect(next[0].content.content).toContain('boom')
    }
  })
})

describe('user message helpers', () => {
  it('appends a user message', () => {
    const next = reduceAppendUserMessage([], 'hi', 1700)
    expect(next).toHaveLength(1)
    if (next[0].type === 'user') {
      expect(next[0].content.content).toBe('hi')
      expect(next[0].content.timestamp).toBe(1700)
    }
  })

  it('appends an attachments row', () => {
    const files = [
      {
        file_id: 'f1',
        filename: 'a.txt',
        content_type: 'text/plain',
        size: 10,
        upload_date: '2026',
      },
    ]
    const next = reduceAppendUserAttachments([], files, 1700)
    expect(next).toHaveLength(1)
    if (next[0].type === 'attachments') {
      expect(next[0].content.role).toBe('user')
      expect(next[0].content.attachments).toEqual(files)
    }
  })

  it('truncates at the user message with the matching event_id', () => {
    const prev: Message[] = [
      { type: 'user', content: { event_id: 'u1', content: 'first', timestamp: 1 } },
      { type: 'assistant', content: { content: 'reply', timestamp: 2 } },
      { type: 'user', content: { event_id: 'u2', content: 'second', timestamp: 3 } },
      { type: 'assistant', content: { content: 'reply2', timestamp: 4 } },
    ]
    const next = reduceTruncateAtUserEvent(prev, 'u2')
    expect(next).toHaveLength(2)
    if (next[1].type === 'assistant') expect(next[1].content.content).toBe('reply')
  })

  it('returns prev unchanged when no match', () => {
    const prev: Message[] = [
      { type: 'user', content: { event_id: 'u1', content: 'x', timestamp: 1 } },
    ]
    expect(reduceTruncateAtUserEvent(prev, 'never')).toBe(prev)
  })
})
