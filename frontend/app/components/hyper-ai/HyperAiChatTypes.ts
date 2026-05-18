export interface Conversation {
  id: number
  title: string
  message_count: number
  is_bot_conversation?: boolean
  updated_at: string
}

export interface ToolCallEntry {
  type: 'tool_call' | 'tool_result' | 'reasoning' | 'subagent_progress' | 'confirmation_required' | 'tool_error'
  name?: string
  tool?: string
  args?: Record<string, unknown>
  result?: string
  content?: string
  subagent?: string
  step?: string
  round?: number
  max_rounds?: number
  taskId?: string
  confirmationId?: string
  description?: string
  status?: 'pending' | 'confirmed' | 'cancelled' | 'failed'
  message?: string
  severity?: string
  resultStatus?: string
  code?: string
  durationMs?: number
  parallel?: boolean
}

export interface ToolCallLogEntry {
  tool: string
  args: Record<string, unknown>
  result: string
  status?: string
  code?: string
  retryable?: boolean
  risk_level?: string
  risk_reason?: string
  message?: string
  duration_ms?: number
  schema_validated?: boolean
  concurrency_safe?: boolean
  execution_mode?: string
}

export interface ChatImageAttachment {
  id: string
  name: string
  mime_type: string
  data_url: string
  size: number
}

export interface CreatedEntityCard {
  type: 'prompt' | 'program' | 'signal_pool' | 'ai_trader' | 'factor'
  id: number
  name: string
  content?: string
  viewUrl: string
}

export interface Message {
  id?: number
  role: 'user' | 'assistant'
  content: string
  reasoning_snapshot?: string
  tool_calls_log?: string
  is_complete?: boolean
  interrupt_reason?: string
  created_at?: string
  isStreaming?: boolean
  statusText?: string
  toolCalls?: ToolCallEntry[]
  isInterrupted?: boolean
  interruptedRound?: number
  attachments?: ChatImageAttachment[]
}
