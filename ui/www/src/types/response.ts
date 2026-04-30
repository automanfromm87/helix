import type { AgentSSEEvent } from './event'

export enum SessionStatus {
  PENDING = 'pending',
  RUNNING = 'running',
  WAITING = 'waiting',
  COMPLETED = 'completed',
  // Backend caught an unhandled exception (code bug, transient infra
  // failure, hot-reload mid-flight). The next backend boot will
  // auto-resume the session if the underlying issue is fixed.
  INTERRUPTED = 'interrupted',
}

export interface CreateSessionResponse {
  session_id: string
  project_id: string | null
}

export interface GetSessionResponse {
  session_id: string
  project_id: string | null
  title: string | null
  status: SessionStatus
  events: AgentSSEEvent[]
  is_shared: boolean
}

export interface ListSessionItem {
  session_id: string
  project_id: string | null
  title: string | null
  latest_message: string | null
  latest_message_at: number | null
  status: SessionStatus
  unread_message_count: number
  is_shared: boolean
}

export interface ProjectItem {
  project_id: string
  name: string
  system_prompt: string | null
  // Each project has exactly one chat session in the 1:1 model.
  session_id: string | null
  title: string | null
  latest_message: string | null
  latest_message_at: number | null
  status: SessionStatus | null
  unread_message_count: number
  is_shared: boolean
}

export interface ListProjectsResponse {
  projects: ProjectItem[]
}

export interface CreateProjectResponse {
  project_id: string
  name: string
  system_prompt: string | null
  session_id: string
}

export interface ListSessionResponse {
  sessions: ListSessionItem[]
}

export interface ConsoleRecord {
  ps1: string
  command: string
  output: string
}

export interface ShellViewResponse {
  output: string
  session_id: string
  console: ConsoleRecord[]
}

export interface FileViewResponse {
  content: string
  file: string
}

export interface SignedUrlResponse {
  signed_url: string
  expires_in: number
}

export interface ShareSessionResponse {
  session_id: string
  is_shared: boolean
}

export interface SharedSessionResponse {
  session_id: string
  title: string | null
  status: SessionStatus
  events: AgentSSEEvent[]
  is_shared: boolean
}

export type SkillSource = 'file' | 'global' | 'project'

export interface SkillItem {
  name: string
  description: string
  body: string
  source: SkillSource
}

export interface ListSkillsResponse {
  skills: SkillItem[]
}
